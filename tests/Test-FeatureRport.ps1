# Prompt user for API key securely
$arguments = @(
# The '--model gpt-4o-mini' argument specifies the OpenAI model used for summarization.
# Ensure the model is supported and available in your OpenAI account; model choice affects output quality and cost.
python scripts/generate_feature_reports.py `
  --master output/roadmap_report_master.csv `
  --fetch-public `
  --use-openai --model gpt-4o-mini `
  --prompt prompts/feature_summarize_tailored.md `
  --out output/roadmap_report.md
  "gpt-4o-mini"
  "--out"
  "output/Test-FeatureRport.md"
)
python $arguments
