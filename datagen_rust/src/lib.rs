#![recursion_limit = "256"]

pub mod catalog;
pub mod cli;
pub mod compare;
pub mod config;
pub mod contracts;
pub mod deterministic;
pub mod engine;
pub mod manifest;
pub mod projection;
pub mod simulation;
pub mod spool;
pub mod telemetry;
pub mod writer;

pub const ENGINE_VERSION: &str = env!("CARGO_PKG_VERSION");
pub const GENERATOR_VERSION: &str = "rust-0.1.4";
pub const SOURCE_SPEC_VERSION: &str = "retail-source-config/v13";
