package httpapi

import (
	"context"
	"net/http"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/aarv/plugins/cors"
	openapiui "github.com/nilshah80/aarv/plugins/openapi-ui"
	"github.com/nilshah80/retail-intelligence/api/internal/execution"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

func New(
	store *readmodel.Store,
	forecast *readmodel.ForecastStore,
	inventory *readmodel.InventoryStore,
	profile execution.Resolved,
	openAPISpec []byte,
	scenarioStores ...*readmodel.ScenarioStore,
) (*aarv.App, error) {
	scenario := readmodel.LoadScenario(context.Background(), readmodel.ScenarioConfig{})
	if len(scenarioStores) > 0 && scenarioStores[0] != nil {
		scenario = scenarioStores[0]
	}
	pricing := readmodel.LoadPricing(context.Background(), readmodel.PricingConfig{})
	return newApp(store, forecast, inventory, profile, openAPISpec, scenario, pricing)
}

func NewWithPricing(
	store *readmodel.Store,
	forecast *readmodel.ForecastStore,
	inventory *readmodel.InventoryStore,
	profile execution.Resolved,
	openAPISpec []byte,
	scenario *readmodel.ScenarioStore,
	pricing *readmodel.PricingStore,
) (*aarv.App, error) {
	return newApp(store, forecast, inventory, profile, openAPISpec, scenario, pricing)
}

func newApp(
	store *readmodel.Store,
	forecast *readmodel.ForecastStore,
	inventory *readmodel.InventoryStore,
	profile execution.Resolved,
	openAPISpec []byte,
	scenario *readmodel.ScenarioStore,
	pricing *readmodel.PricingStore,
) (*aarv.App, error) {
	app := aarv.New(aarv.WithBanner(false))
	permits := make(chan struct{}, profile.API.HTTPConcurrency)
	app.Use(cors.New(cors.Config{
		AllowOrigins: []string{"http://127.0.0.1:5173", "http://localhost:5173"},
		AllowMethods: []string{"GET", "POST", "OPTIONS"},
		AllowHeaders: []string{"Origin", "Accept", "Content-Type"},
		ExposeHeaders: []string{
			"Content-Disposition", "X-Export-Count", "X-Export-ID", "X-Scope-Revision",
		},
		MaxAge: 600,
	}))
	app.Use(aarv.WrapMiddleware(func(next aarv.HandlerFunc) aarv.HandlerFunc {
		return func(c *aarv.Context) error {
			permits <- struct{}{}
			defer func() { <-permits }()
			return next(c)
		}
	}))

	app.Get("/healthz", func(c *aarv.Context) error {
		return c.JSON(http.StatusOK, map[string]any{
			"status":  "ok",
			"profile": profile,
		})
	})
	app.Get("/api/v1/data-management/summary", func(c *aarv.Context) error {
		return c.JSON(http.StatusOK, store.Summary())
	})
	app.Get("/api/v1/data-management/dashboard", func(c *aarv.Context) error {
		return c.JSON(http.StatusOK, store.Dashboard())
	})
	app.Get("/api/v1/fx/rates", func(c *aarv.Context) error {
		return c.JSON(http.StatusOK, store.FX())
	})
	app.Get("/api/v1/data-management/gates", func(c *aarv.Context) error {
		return c.JSON(http.StatusOK, store.Gates())
	})
	app.Get("/api/v1/data-management/capabilities", func(c *aarv.Context) error {
		return c.JSON(http.StatusOK, store.Capabilities())
	})
	app.Get("/api/v1/data-management/reconciliation", func(c *aarv.Context) error {
		return c.JSON(http.StatusOK, store.Reconciliation())
	})
	app.Get("/api/v1/data-management/quality-findings", func(c *aarv.Context) error {
		return c.JSON(http.StatusOK, store.QualityFindings())
	})
	mountForecastRoutes(app, forecast)
	mountInventoryRoutes(app, inventory)
	mountScenarioRoutes(app, scenario)
	mountPricingRoutes(app, pricing)
	mountDirectExportRoute(app, forecast, inventory, pricing)
	app.Get("/openapi.yaml", func(c *aarv.Context) error {
		return c.Blob(
			http.StatusOK,
			"application/yaml; charset=utf-8",
			openAPISpec,
		)
	})
	if err := openapiui.Mount(app, openapiui.Config{
		SpecURL:     "/openapi.yaml",
		Title:       "Retail Intelligence API",
		SwaggerPath: "/docs",
		ReDocPath:   "/redoc",
	}); err != nil {
		return nil, err
	}
	return app, nil
}
