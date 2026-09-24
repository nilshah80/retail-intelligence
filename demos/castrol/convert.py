"""Offline, clone-only Castrol presentation projection; never targets the Gulf DB."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / '.serve-runtime/castrol-demo'
DSN = 'postgresql://retail:castrol-demo-local-only@127.0.0.1:55432/retail_intelligence'
DEFAULT_BACKUP = Path('/Volumes/ExpM2/retail-intelligence/run-73ba460b02d63c40/gulf-rust-perf1-20260924-182307-IST')
DISCLOSURE = ('Castrol presentation projection. Product family names are references; '
              'SKU codes, grades, packs, locations, prices and business results are synthetic. '
              'Source model evidence is retained as provenance, not a new Castrol model validation.')


def log(message):
    print(message, flush=True)


def mapping(conn):
    catalog = json.loads((HERE / 'product-map.json').read_text())
    products = conn.execute('SELECT DISTINCT sku_id, product_name FROM retail_serving.forecast_series_dimensions ORDER BY sku_id').fetchall()
    names = catalog['productMap']
    assert set(p['product_name'] for p in products) == set(names), 'Product map does not cover the source catalog exactly'
    replacements = {old: new or 'Excluded demo product' for old, new in names.items()}
    excluded = []
    for index, row in enumerate(products, 1):
        if names[row['product_name']] is None:
            excluded.append(row['sku_id'])
        replacements[row['sku_id']] = f'castrol-india:CST-{index:04d}'
    for index, (name, note) in enumerate(sorted(catalog['productNotes'].items()), 1):
        code = note.get('sourceProductCode')
        if code:
            replacements[code] = f'CST-FAMILY-{index:03d}'
    replacements.update({'Gulf India': 'Castrol India', 'Gulf Direct Online': 'Castrol Online'})
    # A single, longest-first expression also transforms identifiers embedded in JSON strings.
    pattern = re.compile('|'.join(re.escape(k) for k in sorted(replacements, key=len, reverse=True)))

    def transform(value):
        if isinstance(value, dict):
            return {transform(k): transform(v) for k, v in value.items()}
        if isinstance(value, list):
            return [transform(v) for v in value]
        if isinstance(value, tuple):
            return tuple(transform(v) for v in value)
        if not isinstance(value, str):
            return value
        value = pattern.sub(lambda m: replacements[m.group()], value)
        for old, new in [('GULF', 'CASTROL'), ('Gulf', 'Castrol'), ('gulf', 'castrol'), ('GLF', 'CST'), ('glf', 'cst')]:
            value = value.replace(old, new)
        return value
    return catalog, products, replacements, excluded, transform


def install_transform(conn, replacements):
    # Literal parameters are quoted by psycopg, never interpolated as SQL code.
    regex = '|'.join(re.escape(k) for k in sorted(replacements, key=len, reverse=True))
    body = '''
    DECLARE value text := input; direct text; part text[];
      lookup constant jsonb := %s;
    BEGIN
      IF value IS NULL OR value !~* '(gulf|glf)' THEN RETURN value; END IF;
      direct := lookup ->> value;
      IF direct IS NOT NULL THEN RETURN direct; END IF;
      IF value LIKE '%%GLF%%' OR value LIKE '%%Gulf %%' THEN
        FOR part IN SELECT regexp_matches(value, %s, 'g') LOOP
          value := replace(value, part[1], lookup ->> part[1]);
        END LOOP;
      END IF;
      RETURN replace(replace(replace(replace(replace(replace(value,
        'GULF','CASTROL'),'Gulf','Castrol'),'gulf','castrol'),'GLF','CST'),'glf','cst'),'Glf','Cst');
    END
    ''' % (sql.Literal(json.dumps(replacements)).as_string(conn), sql.Literal('(' + regex + ')').as_string(conn))
    conn.execute(sql.SQL('CREATE FUNCTION pg_temp.demo_text(input text) RETURNS text LANGUAGE plpgsql IMMUTABLE AS {}').format(sql.Literal(body)))


def schema(conn):
    return conn.execute("""SELECT table_name,column_name,data_type,udt_name
      FROM information_schema.columns WHERE table_schema='retail_serving'
      AND table_name IN (SELECT tablename FROM pg_tables WHERE schemaname='retail_serving')
      ORDER BY table_name,ordinal_position""").fetchall()


def exclude_products(conn, columns, excluded):
    counts = {}
    for table in sorted({r['table_name'] for r in columns if r['column_name'] == 'sku_id'}):
        result = conn.execute(sql.SQL('DELETE FROM retail_serving.{} WHERE sku_id=ANY(%s)').format(sql.Identifier(table)), (excluded,))
        counts[table] = result.rowcount
    expression = '|'.join(re.escape(sku) for sku in excluded)
    for table, column in [('forecast_drivers', 'scope'), ('forecast_metrics', 'slice_id')]:
        result = conn.execute(sql.SQL('DELETE FROM retail_serving.{} WHERE {} ~ %s').format(sql.Identifier(table), sql.Identifier(column)), (expression,))
        counts[table] = result.rowcount
    return counts


def rewrite_columns(conn, columns, transform, *, source_pattern=r'gulf|glf', force_maps=False):
    """Rewrite fact rows through exact maps, not millions of PL/pgSQL calls.

    Only distinct branded values are transformed. A map also retains distinct
    identity values for a partly branded column, allowing one ordinary equality
    join per column instead of a second copy of the fact table for LEFT JOINs.
    Null has a separate tagged join key and remains null. Large JSON values need
    no btree key/index: PostgreSQL can hash-join the analyzed temporary maps.
    """
    counts = {}
    fast_tables = {'forecast_eval_predictions', 'forecast_metrics', 'forecast_series',
                   'executive_sales', 'forecast_drivers'}
    supported = {'text', 'varchar', 'json', 'jsonb', '_text'}
    branded = re.compile(source_pattern, re.I)
    for table in sorted({r['table_name'] for r in columns}):
        text_columns = [r for r in columns if r['table_name'] == table and r['udt_name'] in supported]
        if not text_columns:
            continue
        relation = sql.Identifier('retail_serving', table)
        large = force_maps or table in fast_tables
        if not large:
            large = conn.execute(sql.SQL(
                'SELECT count(*) AS n FROM (SELECT 1 FROM {} LIMIT 100001) bounded'
            ).format(relation)).fetchone()['n'] > 100000
        if large:
            maps, assignments, joins, changed = [], [], [], []
            for column_index, c in enumerate(text_columns):
                column = sql.Identifier(c['column_name'])
                values = conn.execute(sql.SQL(
                    'SELECT DISTINCT {}::text AS value FROM {}'
                ).format(column, relation)).fetchall()
                entries = []
                changed_values = 0
                nullable = any(row['value'] is None for row in values)
                for row in values:
                    old = row['value']
                    new = transform(old) if old is not None and branded.search(old) else old
                    is_changed = old != new
                    changed_values += is_changed
                    key = ('N' if old is None else 'V' + old) if nullable else old
                    entries.append((key, new, is_changed))
                if not changed_values:
                    continue
                map_name = f'castrol_value_map_{column_index}'
                map_relation = sql.Identifier('pg_temp', map_name)
                conn.execute(sql.SQL(
                    'CREATE TEMP TABLE {} (old_value text NOT NULL, new_value text, '
                    'changed boolean NOT NULL) ON COMMIT DROP'
                ).format(sql.Identifier(map_name)))
                with conn.cursor() as cursor:
                    with cursor.copy(sql.SQL('COPY {} FROM STDIN').format(map_relation)) as copy:
                        for entry in entries:
                            copy.write_row(entry)
                conn.execute(sql.SQL('ANALYZE {}').format(map_relation))
                alias = sql.Identifier(f'm{column_index}')
                source_value = sql.SQL('t.{}::text').format(column)
                if nullable:
                    source_value = sql.SQL("coalesce('V' || {}, 'N')").format(source_value)
                maps.append((map_relation, alias))
                assignments.append(sql.SQL('{}={}.new_value::{}').format(
                    column, alias, sql.SQL(c['udt_name'])))
                joins.append(sql.SQL('{}={}.old_value').format(source_value, alias))
                changed.append(sql.SQL('{}.changed').format(alias))
                log(f'Mapped {table}.{c["column_name"]}: {changed_values:,} distinct changed values')
            if maps:
                result = conn.execute(sql.SQL(
                    'UPDATE {} AS t SET {} FROM {} WHERE {} AND ({})'
                ).format(
                    relation, sql.SQL(',').join(assignments),
                    sql.SQL(',').join(sql.SQL('{} AS {}').format(name, alias) for name, alias in maps),
                    sql.SQL(' AND ').join(joins), sql.SQL(' OR ').join(changed),
                ))
                counts[table] = result.rowcount
                for map_relation, _ in maps:
                    conn.execute(sql.SQL('DROP TABLE {}').format(map_relation))
            else:
                counts[table] = 0
            log(f'Converted {table}: {counts[table]:,} rows (exact-map joins)')
            continue
        assignments, predicates = [], []
        for c in text_columns:
            kind = c['udt_name']
            column = sql.Identifier(c['column_name'])
            if kind == '_text':
                expr = sql.SQL('CASE WHEN {} IS NULL THEN NULL ELSE ARRAY(SELECT pg_temp.demo_text(v) FROM unnest({}) v) END').format(column,column)
            else:
                expr = sql.SQL('pg_temp.demo_text({}::text)::{}').format(column, sql.SQL(kind))
            predicate = sql.SQL("{}::text ~* '(gulf|glf)'").format(column)
            assignments.append(sql.SQL('{}=CASE WHEN {} THEN {} ELSE {} END').format(
                column, predicate, expr, column))
            predicates.append(predicate)
        if assignments:
            result = conn.execute(sql.SQL('UPDATE retail_serving.{} SET {} WHERE {}').format(
                sql.Identifier(table), sql.SQL(',').join(assignments), sql.SQL(' OR ').join(predicates)))
            counts[table] = result.rowcount
            log(f'Converted {table}: {result.rowcount:,} rows')
    return counts


def competitors(conn):
    removed = conn.execute("""DELETE FROM retail_serving.pricing_competitor_assessments
      WHERE competitor_id ~* '(castrol|gulf)' OR details->>'competitor_brand' ~* '(castrol|gulf)'
         OR details->>'competitor_product_title' ~* '(castrol|gulf)'""").rowcount
    # Match IDs in the source were reused across geography. Unique scoped IDs avoid
    # duplicate UI keys without changing the generic UI or detail endpoint.
    conn.execute("""UPDATE retail_serving.pricing_competitor_assessments SET
      match_id='match:' || sku_id || ':' || competitor_id || ':' || geo_scope_type || ':' || geo_scope_id,
      details=(details::jsonb || jsonb_build_object(
        'match_id','match:' || sku_id || ':' || competitor_id || ':' || geo_scope_type || ':' || geo_scope_id,
        'competitor_model',competitor_product_id,
        'competitor_name',details->>'competitor_brand'))::json""")
    conn.execute("""UPDATE retail_serving.price_recommendations r SET details=
      jsonb_set(r.details::jsonb,'{lineage}',to_jsonb(
        (jsonb_set((r.details->>'lineage')::jsonb,'{competitorMatchId}',to_jsonb(c.match_id)))::text))::json
      FROM retail_serving.pricing_competitor_assessments c
      WHERE r.bundle_id=c.bundle_id AND r.sku_id=c.sku_id AND r.market_id=c.market_id
        AND r.store_id=c.geo_scope_id AND r.competitor_price_minor IS NOT NULL
        AND r.details->>'lineage' IS NOT NULL""")
    return removed


def refresh_counts(conn):
    for record in conn.execute('SELECT bundle_id,capabilities FROM retail_serving.pricing_materializations').fetchall():
        bundle_id=record['bundle_id']
        accepted=conn.execute("""SELECT count(*) AS n
          FROM retail_serving.pricing_response_assessments
          WHERE bundle_id=%s AND disposition='accepted'""",(bundle_id,)).fetchone()['n']
        row=conn.execute("""SELECT count(*) AS actionable
          FROM retail_serving.price_recommendations WHERE bundle_id=%s
          AND record_kind='recommendation' AND action IN ('Increase','Decrease')""",(bundle_id,)).fetchone()
        rivals=conn.execute("""SELECT count(*) AS total,count(*) FILTER(WHERE bound_eligible) AS eligible
          FROM retail_serving.pricing_competitor_assessments WHERE bundle_id=%s""",(bundle_id,)).fetchone()
        caps=record['capabilities']
        # Response acceptance precedes inventory/promotion/margin guardrails.
        # An accepted fitted response can still produce a withheld recommendation.
        caps['priceResponse']['acceptedRows']=accepted
        caps['priceRevenue']['actionableRows']=row['actionable']
        caps['competitorMonitor']['descriptiveRows']=rivals['total']
        caps['competitorMonitor']['available']=rivals['total']>0
        caps['competitorResponse']['eligibleBounds']=rivals['eligible']
        caps['competitorResponse']['available']=rivals['eligible']>0
        conn.execute('UPDATE retail_serving.pricing_materializations SET capabilities=%s WHERE bundle_id=%s',(Jsonb(caps),bundle_id))
    for record in conn.execute('SELECT scenario_context_version,manifest FROM retail_serving.forecast_scenario_contexts').fetchall():
        version=record['scenario_context_version']
        manifest=record['manifest']
        manifest['rowCounts']={
            'forecastHorizon':conn.execute('SELECT count(*) AS n FROM retail_serving.forecast_scenario_horizon_rows WHERE scenario_context_version=%s',(version,)).fetchone()['n'],
            'seriesCommercial':conn.execute('SELECT count(*) AS n FROM retail_serving.forecast_scenario_commercial_rows WHERE scenario_context_version=%s',(version,)).fetchone()['n']}
        conn.execute('UPDATE retail_serving.forecast_scenario_contexts SET manifest=%s WHERE scenario_context_version=%s',(Jsonb(manifest),version))
    for record in conn.execute('SELECT inventory_extension_version,manifest FROM retail_serving.forecast_scenario_inventory_extensions').fetchall():
        version=record['inventory_extension_version']
        manifest=record['manifest']
        manifest['rowCounts']={
            'inventoryNode':conn.execute('SELECT count(*) AS n FROM retail_serving.forecast_scenario_inventory_node_rows WHERE inventory_extension_version=%s',(version,)).fetchone()['n'],
            'inventorySeries':conn.execute('SELECT count(*) AS n FROM retail_serving.forecast_scenario_inventory_series_rows WHERE inventory_extension_version=%s',(version,)).fetchone()['n']}
        conn.execute('UPDATE retail_serving.forecast_scenario_inventory_extensions SET manifest=%s WHERE inventory_extension_version=%s',(Jsonb(manifest),version))


def validate(conn, columns, excluded, transform):
    checks = []
    for table in sorted({r['table_name'] for r in columns}):
        predicates = [sql.SQL("{}::text ~* '(gulf|glf|demo)' ").format(sql.Identifier(c['column_name']))
                      for c in columns if c['table_name'] == table and c['udt_name'] in ('text','varchar','json','jsonb','_text')]
        if not predicates:
            continue
        n = conn.execute(sql.SQL('SELECT count(*) AS n FROM retail_serving.{} WHERE {}').format(
            sql.Identifier(table), sql.SQL(' OR ').join(predicates))).fetchone()['n']
        checks.append({'check': 'brand-leaks', 'table': table, 'count': n, 'passed': n == 0})
    fks = conn.execute("""SELECT c.conname, c.conrelid::regclass::text AS child,
      c.confrelid::regclass::text AS parent,
      ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(num,ord)
        JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num ORDER BY k.ord) AS child_cols,
      ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(num,ord)
        JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.num ORDER BY k.ord) AS parent_cols
      FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
      WHERE n.nspname='retail_serving' AND c.contype='f'""").fetchall()
    for fk in fks:
        join = sql.SQL(' AND ').join(sql.SQL('p.{}=c.{}').format(sql.Identifier(p), sql.Identifier(c)) for c,p in zip(fk['child_cols'],fk['parent_cols']))
        nonnull = sql.SQL(' AND ').join(sql.SQL('c.{} IS NOT NULL').format(sql.Identifier(c)) for c in fk['child_cols'])
        n = conn.execute(sql.SQL('SELECT count(*) AS n FROM {} c WHERE {} AND NOT EXISTS(SELECT 1 FROM {} p WHERE {})').format(
            sql.Identifier(*fk['child'].split('.')), nonnull, sql.Identifier(*fk['parent'].split('.')), join)).fetchone()['n']
        checks.append({'check': 'foreign-key', 'constraint': fk['conname'], 'orphans': n, 'passed': n == 0})
    n = conn.execute("SELECT count(*) AS n FROM retail_serving.pricing_competitor_assessments WHERE competitor_id ~* '(castrol|gulf)' OR details->>'competitor_brand' ~* '(castrol|gulf)' OR details->>'competitor_product_title' ~* '(castrol|gulf)'").fetchone()['n']
    checks.append({'check': 'excluded-competitors', 'count': n, 'passed': n == 0})
    n = conn.execute('SELECT count(*)-count(DISTINCT match_id) AS n FROM retail_serving.pricing_competitor_assessments').fetchone()['n']
    checks.append({'check': 'unique-competitor-match-ids', 'duplicates': n, 'passed': n == 0})
    for table in sorted({r['table_name'] for r in columns if r['column_name']=='sku_id'}):
        n = conn.execute(sql.SQL('SELECT count(*) AS n FROM retail_serving.{} WHERE sku_id=ANY(%s)').format(sql.Identifier(table)), ([transform(s) for s in excluded],)).fetchone()['n']
        checks.append({'check': 'excluded-products', 'table': table, 'count': n, 'passed': n == 0})
    failed = [c for c in checks if not c['passed']]
    assert not failed, json.dumps(failed)
    return checks


def write_runtime(backup, conn, transform, report):
    from clean_labels import cleanup
    target = RUNTIME / 'runtime'; target.mkdir(parents=True, exist_ok=True)
    for source, filename in [('runtime/evidence/gate-a.json','gate-a.json'), ('runtime/evidence/gate-b.json','gate-b.json'),
                             ('runtime/curated/publication-manifest.json','publication-manifest.json'),
                             ('runtime/pricing/pricing-serving.json','pricing-serving.json')]:
        content = cleanup(transform(json.loads((backup/source).read_text())))
        if filename != 'pricing-serving.json':
            content['adaptation'] = {'name':'Castrol disposable environment','disclosure':DISCLOSURE,'sourceRunId':report['sourceRunId']}
        else:
            identity={k:v for k,v in content.items() if k!='configFingerprint'}
            content['configFingerprint']=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if filename == 'publication-manifest.json':
            controls=content['businessControls']
            categories={r['category'] for r in conn.execute('SELECT DISTINCT category FROM retail_serving.forecast_series')}
            controls['categories']=[c for c in controls['categories'] if c['categoryId'] in categories]
            controls['totalSkus']=controls['activeSkus']=report['retainedSkuCount']
        assert not re.search(r'gulf|glf|demo',json.dumps(content),re.I), f'Runtime leak in {filename}'
        (target/filename).write_text(json.dumps(content,indent=2,ensure_ascii=False)+'\n')


def convert(backup=DEFAULT_BACKUP):
    from clean_labels import cleanup
    from pricing_refresh import prepare, apply
    from refresh import refresh
    from postcheck import finalize, audit
    from presentation import apply as apply_presentation
    RUNTIME.mkdir(parents=True,exist_ok=True); (RUNTIME/'validation').mkdir(exist_ok=True)
    source=json.loads((backup/'backup-manifest.json').read_text())
    with psycopg.connect(DSN,row_factory=dict_row,application_name='castrol-demo-conversion') as conn:
        assert conn.info.host=='127.0.0.1' and conn.info.port==55432 and conn.info.dbname=='retail_intelligence'
        assert conn.execute("SELECT to_regnamespace('castrol_demo') AS n").fetchone()['n'] is None, 'Already converted; discard the demo volume to rebuild'
        original=conn.execute('SELECT * FROM retail_serving.active_forecast_versions').fetchall()
        assert len(original)==1 and original[0]['markets']==['gulf-india']
        assert original[0]['run_semantic_fingerprint']==source['forecast'][0]['run_semantic_fingerprint']
        cols=schema(conn)
        catalog,products,replacements,excluded,transform=mapping(conn)
        log('Preparing pricing without self-competitor bounds')
        prepared=prepare(conn,excluded)
        # This transaction runs only in the dedicated, offline demo clone. Original
        # table definitions/checks are retained; FK joins are checked before commit.
        conn.execute('SET LOCAL session_replication_role=replica')
        conn.execute('SET LOCAL statement_timeout=0')
        install_transform(conn,replacements)
        deleted=exclude_products(conn,cols,excluded)
        rewritten=rewrite_columns(conn,cols,transform)
        log('Applying recalculated pricing')
        pricing_result=apply(conn,prepared,transform)
        competitors_removed=competitors(conn)
        log('Refreshing aggregates for retained products')
        aggregate_result=refresh(conn,excluded,transform)
        finalization_result=finalize(conn)
        refresh_counts(conn)
        # Explain synthetic provenance through the existing scenario disclosure.
        conn.execute('UPDATE retail_serving.forecast_scenario_assumption_sets SET disclosure=%s',(DISCLOSURE,))
        conn.execute("UPDATE retail_serving.replenishment_suppliers SET supplier_name='Castrol Distributor', category_label=regexp_replace(category_label,'^Castrol - ', '')")
        presentation_result=apply_presentation(conn,backup/'runtime/curated/publication-manifest.json')
        log('Removing presentation-only demo wording and identifiers')
        label_rewrites=rewrite_columns(conn,cols,cleanup,source_pattern='demo',force_maps=True)
        conn.execute('SET LOCAL session_replication_role=origin')
        log('Validating all table identities and foreign-key links')
        checks=validate(conn,cols,excluded,transform)
        checks.extend(presentation_result['checks'])
        audit_result=audit(conn)
        checks.extend(audit_result['checks'])
        checks.append({'check':'session-replication-role-restored',
                       'observed':audit_result['sessionReplicationRole'],
                       'passed':audit_result['sessionReplicationRole']=='origin'})
        assert all(c['passed'] for c in checks), json.dumps([c for c in checks if not c['passed']])
        rows={t:conn.execute(sql.SQL('SELECT count(*) AS n FROM retail_serving.{}').format(sql.Identifier(t))).fetchone()['n'] for t in sorted({r['table_name'] for r in cols})}
        kept=conn.execute('SELECT count(DISTINCT sku_id) AS n FROM retail_serving.forecast_series_dimensions').fetchone()['n']
        report={'createdAt':datetime.now(timezone.utc).isoformat(),'sourceRunId':source['sourceRunId'],
                'sourceCommit':source['gitCommit'],'disclosure':DISCLOSURE,'sourceSkuCount':len(products),'retainedSkuCount':kept,
                'skuIdentityMap':{p['sku_id']:replacements[p['sku_id']] for p in products},
                'excludedSkus':excluded,'excludedProducts':[k for k,v in catalog['productMap'].items() if v is None],
                'rowCounts':rows,'deletedRows':deleted,'rewrittenRows':rewritten,'competitorRowsRemoved':competitors_removed,
                'pricing':pricing_result,'aggregates':aggregate_result,
                'presentation':presentation_result,'labelRewrites':label_rewrites,
                'finalization':finalization_result,'audit':audit_result,'checks':checks,'passed':True,
                'provenancePolicy':'Original opaque model/evidence fingerprints identify the source baseline. Demo adaptation is separately recorded; no retraining or source certification is claimed.'}
        conn.execute('CREATE SCHEMA castrol_demo')
        conn.execute('CREATE TABLE castrol_demo.adaptation (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), report jsonb NOT NULL)')
        conn.execute('INSERT INTO castrol_demo.adaptation(report) VALUES(%s)',(Jsonb(report),))
        conn.execute('SET LOCAL session_replication_role=origin')
        write_runtime(backup,conn,transform,report)
    (RUNTIME/'validation/conversion.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    log(json.dumps({'converted':True,'retainedSkus':kept,'removedCompetitorRows':competitors_removed}))
    return report


if __name__=='__main__':
    convert(Path(sys.argv[1]) if len(sys.argv)>1 else DEFAULT_BACKUP)
