"""Apply friendly labels to the isolated demo's existing read-model fields.

The caller owns the guarded conversion transaction. No application source,
canonical dataset, numeric fact, authority identity or business city is changed.
"""

from __future__ import annotations

import json
from pathlib import Path

from psycopg import sql
from psycopg.rows import tuple_row


PLANT_LABELS = {
    "Chennai (Ennore) Blending Plant": "Chennai Distribution Hub",
    "Silvassa Blending Plant": "Western Distribution Hub",
}


def label_maps(publication_manifest):
    """Accept either the original publication or its adapted runtime copy."""
    document = (json.loads(Path(publication_manifest).read_text())
                if not isinstance(publication_manifest, dict) else publication_manifest)
    categories = {}
    aliases = {}
    for category in document["businessControls"]["categories"]:
        identifier = category["categoryId"].replace("gulf", "castrol")
        name = category["name"]
        categories[identifier] = name
        # This is the humanized slug stored by the original inventory publisher.
        # It was previously hidden by a Gulf-specific UI compatibility map.
        aliases[" - ".join(part.title() for part in identifier.split("-"))] = name
    plants = {}
    for old, new in PLANT_LABELS.items():
        plants[old + " (Demo)"] = new
        plants[old] = new
    return categories, aliases, plants


def apply(conn, publication_manifest):
    """Idempotently update only presentation strings in the disposable clone."""
    if (conn.info.host, conn.info.port, conn.info.dbname) != (
        "127.0.0.1", 55432, "retail_intelligence"
    ):
        raise ValueError("Presentation adaptation is restricted to the isolated Castrol database")
    categories, aliases, plants = label_maps(publication_manifest)
    if not categories:
        raise ValueError("The publication has no friendly category labels")
    changes = {}
    checks = []
    with conn.cursor(row_factory=tuple_row) as cursor:
        columns = cursor.execute("""
            SELECT c.table_name,c.column_name,c.udt_name
            FROM information_schema.columns c
            JOIN pg_tables t ON t.schemaname=c.table_schema AND t.tablename=c.table_name
            WHERE c.table_schema='retail_serving'
              AND c.udt_name IN ('text','varchar')
            ORDER BY c.table_name,c.ordinal_position
        """).fetchall()
        table_columns = {}
        for table, column, _ in columns:
            table_columns.setdefault(table, set()).add(column)
        for table, names in table_columns.items():
            if not {'category', 'category_label'} <= names:
                continue
            values = sql.SQL(',').join(sql.SQL('(%s,%s)') for _ in categories)
            parameters = [value for pair in categories.items() for value in pair]
            result = cursor.execute(sql.SQL(
                'UPDATE {} AS t SET category_label=m.label '
                'FROM (VALUES {}) AS m(category,label) '
                'WHERE t.category=m.category AND t.category_label IS DISTINCT FROM m.label'
            ).format(sql.Identifier('retail_serving', table), values), parameters)
            changes[f'{table}.category_label'] = result.rowcount

        for table, column, kind in columns:
            replacements = {}
            if column.endswith('_label'):
                replacements.update(aliases)
            if column == 'name' or column.endswith('_name'):
                replacements.update(plants)
            if not replacements:
                continue
            expression = sql.SQL('{}::text').format(sql.Identifier(column))
            parameters = []
            # Longer plant labels include the existing suffix, preventing a
            # second "(Demo)" when the recipe is re-applied after conversion.
            for old, new in sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True):
                expression = sql.SQL('replace({},%s,%s)').format(expression)
                parameters.extend((old, new))
            patterns = []
            if aliases.keys() & replacements.keys():
                patterns.append('%Castrol - %')
            if plants.keys() & replacements.keys():
                patterns.extend('%' + value + '%' for value in PLANT_LABELS)
            predicate = sql.SQL('{}::text LIKE ANY(%s)').format(sql.Identifier(column))
            result = cursor.execute(sql.SQL(
                'UPDATE {} SET {}={}::{} WHERE {}'
            ).format(sql.Identifier('retail_serving', table), sql.Identifier(column),
                     expression, sql.SQL(kind), predicate), [*parameters, patterns])
            key = f'{table}.{column}'
            changes[key] = changes.get(key, 0) + result.rowcount
            remaining = cursor.execute(sql.SQL(
                'SELECT count(*) FROM {} WHERE {}'
            ).format(sql.Identifier('retail_serving', table), predicate), (patterns,)).fetchone()[0]
            checks.append({'check': 'friendly-presentation-labels', 'field': key,
                           'remainingAliases': remaining, 'passed': remaining == 0})
    failed = [check for check in checks if not check['passed']]
    if failed:
        raise ValueError(f'Unmapped presentation labels remain: {failed}')
    return {'changedRowsByField': changes, 'categoryLabels': categories,
            'locationLabels': PLANT_LABELS, 'checks': checks, 'passed': True}
