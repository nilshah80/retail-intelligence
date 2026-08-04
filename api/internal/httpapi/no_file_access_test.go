package httpapi

// P4-8 task 13: prove the REQUEST path cannot open Parquet or DuckDB, and cannot
// call out to Python.
//
// The dependency list already makes the first half true today -- the module
// requires only pgx, aarv and the OpenAPI UI plugin. That is not the same as
// proving it stays true: adding a DuckDB driver or an os/exec call to a handler
// is a two-line change that reviews cleanly, and the failure it produces is a
// request-time file read on a serving path whose whole contract is "PostgreSQL
// only".
//
// The distinction that matters is startup versus request time, and the first
// version of this test got it wrong -- it flagged main.go, the execution profile
// loader and the data-management store, all of which read files exactly once
// while the process is coming up. Reading a config file at boot is not the defect;
// reading one while answering a request is. So the checks are split:
//
//   - capability imports (DuckDB, Parquet, Arrow, os/exec, net/rpc) are forbidden
//     everywhere in the api tree, because nothing here has a legitimate use for
//     them at any time;
//   - filesystem and subprocess CALLS are forbidden only in the files that
//     execute per request.
//
// And the startup/request split is itself asserted rather than assumed: the
// last test fails if a Load* constructor is ever called from outside cmd/, which
// is what would turn a startup read into a request-time one.

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Import paths no code in this module may reach. Substring matching on purpose:
// a fork, a vendored copy or a wrapper under a different module path is the same
// capability, and matching exact paths would let any of them through.
//
// Deliberately NOT listed: "plugin". aarv's cors and openapi-ui plugins are the
// web framework itself, and the substring matched their import path -- a check
// that fires on the framework it is protecting teaches people to delete it.
var forbiddenImports = []string{
	"duckdb",
	"parquet",
	"arrow",
	"os/exec",
	"net/rpc",
}

// Symbols that reach the filesystem or a subprocess. Forbidden only in
// requestPathFiles below.
var forbiddenCalls = []string{
	"os.Open",
	"os.ReadFile",
	"os.ReadDir",
	"os.OpenFile",
	"exec.Command",
	"exec.CommandContext",
	"ioutil.ReadFile",
}

// Files whose code runs while a request is being answered: the handler
// registrations and their closures, plus the two read models that query per
// request. Everything else in the tree runs once at startup.
var requestPathFiles = []string{
	filepath.Join("internal", "httpapi", "app.go"),
	filepath.Join("internal", "httpapi", "forecast.go"),
	filepath.Join("internal", "httpapi", "inventory.go"),
	filepath.Join("internal", "readmodel", "forecast.go"),
	filepath.Join("internal", "readmodel", "inventory.go"),
}

func apiRoot(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	return root
}

func goSources(t *testing.T, root string) map[string]string {
	t.Helper()
	sources := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() || !strings.HasSuffix(path, ".go") {
			return nil
		}
		if strings.HasSuffix(path, "_test.go") {
			return nil
		}
		relative, relErr := filepath.Rel(root, path)
		if relErr != nil {
			return relErr
		}
		body, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		sources[relative] = string(body)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	// A check that scanned nothing passes silently, which is the one outcome that
	// would make this test worse than not having it.
	if len(sources) < 5 {
		t.Fatalf("found only %d non-test Go files; the walk is not reaching the tree", len(sources))
	}
	return sources
}

func TestNoServingCodeImportsAFileOrSubprocessCapability(t *testing.T) {
	root := apiRoot(t)
	fileSet := token.NewFileSet()
	for relative := range goSources(t, root) {
		parsed, err := parser.ParseFile(
			fileSet, filepath.Join(root, relative), nil, parser.ImportsOnly,
		)
		if err != nil {
			t.Fatalf("%s: %v", relative, err)
		}
		for _, imported := range parsed.Imports {
			value := strings.Trim(imported.Path.Value, `"`)
			for _, forbidden := range forbiddenImports {
				if strings.Contains(value, forbidden) {
					t.Errorf(
						"%s imports %q; serving reads PostgreSQL only, so a %s "+
							"dependency anywhere in this module breaks the contract",
						relative, value, forbidden,
					)
				}
			}
		}
	}
}

func TestTheRequestPathTouchesNoFileAndSpawnsNoProcess(t *testing.T) {
	root := apiRoot(t)
	sources := goSources(t, root)
	for _, relative := range requestPathFiles {
		body, present := sources[relative]
		if !present {
			// A renamed or deleted request-path file must fail loudly. Silently
			// skipping it would leave the handler unchecked under a new name.
			t.Fatalf(
				"%s is listed as request-path code but does not exist; update "+
					"requestPathFiles when handlers move",
				relative,
			)
		}
		for _, call := range forbiddenCalls {
			if strings.Contains(body, call) {
				t.Errorf(
					"%s calls %s at request time; a handler that can open a file "+
						"can serve a value that is not in the activated projection",
					relative, call,
				)
			}
		}
	}
}

func TestStartupOnlyLoadersAreNeverCalledFromServingCode(t *testing.T) {
	// This is what keeps the split above honest. readmodel.Load, LoadForecast and
	// LoadInventory each read files or open a pool; calling one from a handler
	// would make those reads request-time no matter what the file lists say.
	root := apiRoot(t)
	constructors := []string{
		"readmodel.Load(",
		"readmodel.LoadForecast(",
		"readmodel.LoadInventory(",
	}
	callSites := map[string][]string{}
	for relative, body := range goSources(t, root) {
		for _, constructor := range constructors {
			if strings.Contains(body, constructor) {
				callSites[constructor] = append(callSites[constructor], relative)
			}
		}
	}
	for _, constructor := range constructors {
		sites := callSites[constructor]
		if len(sites) == 0 {
			t.Errorf(
				"%s is never called; a read model nothing constructs cannot be "+
					"serving anything",
				constructor,
			)
			continue
		}
		for _, site := range sites {
			if !strings.HasPrefix(site, "cmd"+string(filepath.Separator)) {
				t.Errorf(
					"%s is called from %s; these constructors read files and open "+
						"pools, so they belong to startup in cmd/ only",
					constructor, site,
				)
			}
		}
	}
}

// TestTheForbiddenListsAreNotEmpty guards the guards. Empty lists would make
// both walks above pass over any source at all.
func TestTheForbiddenListsAreNotEmpty(t *testing.T) {
	if len(forbiddenImports) == 0 || len(forbiddenCalls) == 0 || len(requestPathFiles) == 0 {
		t.Fatal("the forbidden and request-path lists must be non-empty to mean anything")
	}
}
