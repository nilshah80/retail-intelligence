package httpapi

import (
	"net/http"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/aarv/plugins/cors"
	"github.com/nilshah80/retail-intelligence/api/internal/execution"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

func New(store *readmodel.Store, profile execution.Resolved) *aarv.App {
	app := aarv.New(aarv.WithBanner(false))
	permits := make(chan struct{}, profile.API.HTTPConcurrency)
	app.Use(cors.New(cors.Config{
		AllowOrigins: []string{"http://127.0.0.1:5173", "http://localhost:5173"},
		AllowMethods: []string{"GET", "OPTIONS"},
		AllowHeaders: []string{"Origin", "Accept", "Content-Type"},
		MaxAge:       600,
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
	return app
}
