use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};

use crate::catalog::{build_catalog, comparison_value};
use crate::compare::compare_runs;
use crate::config::LoadedConfig;
use crate::engine::{ExecutionProfile, ProfileName, generate, named_execution_profiles, plan};
use crate::writer::write_json;
use crate::{GENERATOR_VERSION, SOURCE_SPEC_VERSION};

#[derive(Debug, Parser)]
#[command(name = "retail-datagen-rust", version = GENERATOR_VERSION)]
#[command(about = "Standalone Rust source-shaped retail data generator")]
struct Args {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Print the Python-compatible named datagen execution profiles.
    ExecutionProfiles,
    Validate {
        #[arg(short, long)]
        config: PathBuf,
    },
    Plan {
        #[arg(short, long)]
        config: PathBuf,
        /// Named execution profile. `--profile` remains a compatibility alias.
        #[arg(
            long = "execution-profile",
            alias = "profile",
            value_enum,
            default_value_t = ProfileName::Safe
        )]
        execution_profile: ProfileName,
        /// Python-compatible `retail-execution-profile/v1` YAML or JSON document.
        #[arg(long)]
        execution_profile_file: Option<PathBuf>,
    },
    /// Write the canonical logical catalog used for Python/Rust differential testing.
    CatalogSnapshot {
        #[arg(short, long)]
        config: PathBuf,
        #[arg(short, long)]
        output: PathBuf,
    },
    Generate {
        #[arg(short, long)]
        config: PathBuf,
        /// Base container for this comparison run. Defaults to
        /// `output/<scenarioId>`, matching the retained Python Gulf layout.
        #[arg(long)]
        output_root: Option<PathBuf>,
        /// Named execution profile. `--profile` remains a compatibility alias.
        #[arg(
            long = "execution-profile",
            alias = "profile",
            value_enum,
            default_value_t = ProfileName::Safe
        )]
        execution_profile: ProfileName,
        /// Python-compatible `retail-execution-profile/v1` YAML or JSON document.
        #[arg(long)]
        execution_profile_file: Option<PathBuf>,
    },
    Compare {
        #[arg(long)]
        python_run: PathBuf,
        #[arg(long)]
        rust_run: PathBuf,
        #[arg(long)]
        report: Option<PathBuf>,
    },
}

pub async fn run() -> Result<()> {
    match Args::parse().command {
        Command::ExecutionProfiles => {
            println!(
                "{}",
                serde_json::to_string_pretty(&named_execution_profiles())?
            );
        }
        Command::Validate { config } => {
            let loaded = LoadedConfig::load(config)?;
            println!(
                "{}",
                serde_json::to_string_pretty(&serde_json::json!({
                    "status": "valid",
                    "sourceSpecVersion": SOURCE_SPEC_VERSION,
                    "scenarioId": loaded.scenario.identity.scenario_id,
                    "configHash": loaded.config_hash,
                    "logicalDays": loaded.logical_days(),
                }))?
            );
        }
        Command::Plan {
            config,
            execution_profile,
            execution_profile_file,
        } => {
            let loaded = LoadedConfig::load(config)?;
            let profile = resolve_execution_profile(execution_profile, execution_profile_file)?;
            println!(
                "{}",
                serde_json::to_string_pretty(&plan(&loaded, &profile)?)?
            );
        }
        Command::CatalogSnapshot { config, output } => {
            let loaded = LoadedConfig::load(config)?;
            let catalog = build_catalog(&loaded)?;
            write_json(&output, &comparison_value(&loaded, &catalog))?;
            println!("{}", output.display());
        }
        Command::Generate {
            config,
            output_root,
            execution_profile,
            execution_profile_file,
        } => {
            let loaded = LoadedConfig::load(config)?;
            let profile = resolve_execution_profile(execution_profile, execution_profile_file)?;
            // Deliberately do not inherit output.rootDirectory: a shared config
            // may name a Python parity-evidence tree. Accepted Rust output stays
            // isolated below this crate's Git-ignored output directory.
            let output_root = output_root.unwrap_or_else(|| PathBuf::from("output"));
            let result = generate(loaded, &output_root, profile).await?;
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
        Command::Compare {
            python_run,
            rust_run,
            report,
        } => {
            let comparison = compare_runs(&python_run, &rust_run)?;
            if let Some(path) = report {
                write_json(&path, &comparison)?;
            }
            println!("{}", serde_json::to_string_pretty(&comparison)?);
        }
    }
    Ok(())
}

fn resolve_execution_profile(
    named: ProfileName,
    profile_file: Option<PathBuf>,
) -> Result<ExecutionProfile> {
    profile_file.map_or_else(|| Ok(named.resolve()), ExecutionProfile::load)
}
