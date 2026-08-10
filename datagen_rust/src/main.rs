use retail_datagen_rust::cli;

#[tokio::main(flavor = "multi_thread")]
async fn main() -> anyhow::Result<()> {
    cli::run().await
}
