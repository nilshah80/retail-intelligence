package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/nilshah80/retail-intelligence/api/internal/execution"
	"github.com/nilshah80/retail-intelligence/api/internal/httpapi"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

func main() {
	address := flag.String("address", ":8080", "HTTP listen address")
	gateA := flag.String("gate-a-report", "", "path to the accepted Gate A report")
	gateB := flag.String("gate-b-report", "", "path to the accepted Gate B report")
	publication := flag.String(
		"publication-manifest", "", "path to the curated publication manifest",
	)
	profiles := flag.String(
		"execution-profiles", "", "path to shared execution profiles.json",
	)
	selected := flag.String(
		"execution-profile", "",
		"named execution profile; RETAIL_EXECUTION_PROFILE then safe are fallbacks",
	)
	openAPISpec := flag.String(
		"openapi-spec", "", "path to the authoritative OpenAPI YAML document",
	)
	postgresDSN := flag.String(
		"postgres-dsn",
		os.Getenv("RETAIL_POSTGRES_DSN"),
		"PostgreSQL DSN; RETAIL_POSTGRES_DSN is the recommended source",
	)
	forecastScope := flag.String(
		"forecast-activation-scope",
		os.Getenv("RETAIL_FORECAST_ACTIVATION_SCOPE"),
		"active forecast scope fingerprint",
	)
	flag.Parse()

	if *gateA == "" || *gateB == "" || *publication == "" ||
		*profiles == "" || *openAPISpec == "" {
		fmt.Fprintln(
			os.Stderr,
			"all evidence, execution-profile, and OpenAPI paths are required",
		)
		os.Exit(2)
	}
	profile, err := execution.Load(*profiles, *selected)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	store, err := readmodel.Load(readmodel.Paths{
		GateAReport:         *gateA,
		GateBReport:         *gateB,
		PublicationManifest: *publication,
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	spec, err := os.ReadFile(*openAPISpec)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	forecastLoadContext, cancelForecastLoad := context.WithTimeout(
		context.Background(),
		10*time.Second,
	)
	forecast := readmodel.LoadForecast(forecastLoadContext, readmodel.ForecastConfig{
		PostgresDSN:                    *postgresDSN,
		ExpectedPublicationFingerprint: store.PublicationFingerprint(),
		ActivationScopeFingerprint:     *forecastScope,
		DBReadPool:                     profile.API.DBReadPool,
	})
	cancelForecastLoad()
	defer forecast.Close()
	app, err := httpapi.New(store, forecast, profile, spec)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if err := app.Listen(*address); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
