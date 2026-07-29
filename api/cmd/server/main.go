package main

import (
	"flag"
	"fmt"
	"os"

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
	flag.Parse()

	if *gateA == "" || *gateB == "" || *publication == "" || *profiles == "" {
		fmt.Fprintln(os.Stderr, "all evidence and execution-profile paths are required")
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
	if err := httpapi.New(store, profile).Listen(*address); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
