# News Briefing Generator
An automated tool that fetches, clusters, and summarizes news articles from various RSS feeds to generate a news briefing based on the feed entries of the past hours (configurable). Powered by locally running LLMs through [Ollama](https://ollama.com/). Final briefing is made available as HTML file.

## What's New in 0.1.1
- Added support for OpenAI models

## Installation
Note: Currently only tested on macOS.

### Prerequisites
- Python 3.10+
- pip
- [Ollama](https://ollama.com/) installed
- at least one Ollama model installed (e.g. `ollama pull llama3.1:8b`)

### Option 1: Local Installation
```bash
# Clone the repository
git clone https://github.com/grbtm/news-briefing-generator.git
cd news-briefing-generator

# Create a virtual environment (recommended)
python -m venv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install the package
pip install .

# Or install with test dependencies
pip install ".[test]"
```

### Option 2: Docker Installation
```bash
# Clone the repository
git clone https://github.com/grbtm/news-briefing-generator.git
cd news-briefing-generator

# Build the Docker image
docker compose build
```

## Usage
### Prerequisites 
1.  Make sure that the settings file is placed in: `configs/settings.yaml`
    - you can use the template: `cp configs/settings.example.yaml configs/settings.yaml`
2. The default settings (`configs/settings.example.yaml`) and workflow file (`configs/workflow_configs.yaml`) assume that the Ollama model `'llama3.1:8b'` is available (`ollama pull llama3.1:8b`)
3. Specify your RSS/Atom feeds using either of these methods:
    - Edit the feed list in `configs/settings.yaml` (the default)
    - Place an OPML file in the `feeds/` directory

### Basic Commands
```bash
# Get help
news-briefing --help

# List available workflows
news-briefing list-workflows

# Validate a workflow
news-briefing validate full_auto_briefing

# Run a complete news briefing generation (based on feeds in configs/settings.yaml)
news-briefing run full_auto_briefing

# Run a complete news briefing generation based on feeds from an OPML file in feeds/
news-briefing run --opml=feeds/example.opml full_auto_briefing

# Run a briefing generation with interactive topic selection approval
news-briefing run full_briefing_w_selection_review
```


### Docker Usage
```bash
docker compose run news-briefing [OPTIONS] COMMAND [ARGS]
```
To run a full auto briefing based on feeds from an OPML file:
```bash
docker compose run news-briefing run --opml=feeds/example.opml full_auto_briefing
```
Run a briefing generation with interactive topic selection approval:
```bash
docker compose run news-briefing run full_briefing_w_selection_review
```


## Configuration
General configuration precedence (highest to lowest):
1. Command line arguments
2. Workflow configs (configs/workflow_configs.yaml)
3. Environment variables (NBG_ prefixed)
4. Environment settings (settings.{env}.yaml)
5. Base settings (settings.yaml)
6. Class defaults (defined per Task in src/news_briefing_generator/tasks/)

## Key Configuration Files
- configs/settings.yaml: Core settings including database path, RSS feeds, and default LLM parameters
- configs/workflow_configs.yaml: Define workflows and task configurations

### LLM Configuration
The application supports two LLM providers:

#### Ollama (Default)
```yaml
llm_provider: "ollama"
ollama:
  base_url: "http://localhost:11434"
  model: "llama3.1:8b"
  num_ctx: 12288
  num_predict: 8192
  temperature: 0.3
```

#### OpenAI
```yaml
llm_provider: "openai"
openai:
  api_key: "your-api-key"  # settings.yaml is included in .gitignore
  model: "gpt-3.5-turbo"
  max_tokens: 1024
  temperature: 0.3
```
You can also set your OpenAI API key as an environment variable:
```bash
export NBG_OPENAI_API_KEY="your-api-key"
```

## Project Structure
- news_briefing_generator: Source code
    - cli/: Command-line interface
    - tasks/: Task implementations
    - db/: Database operations
    - model/: Data models
    - llm/: LLM implementation and abstractions
- configs: Configuration files
- briefings: Output directory for generated HTML briefings
- data: Database storage
- logs: Application logs
- feeds: OPML files containing list of feeds

## Important Note About Feed Management
The application uses a single SQLite database to store all feed data. When working with different sets of RSS feeds (e.g., one set for technology news, another for world news), you'll need to use separate databases to keep the data isolated. You can specify a different database path using the --database flag:

```bash
# Use a specific database for tech news feeds
news-briefing run --database tech_news.sqlite --opml tech_feeds.opml full_briefing

# Use another database for world news feeds
news-briefing run --database world_news.sqlite --opml world_feeds.opml full_briefing
```

## Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=news_briefing_generator

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
```

## License
This project is licensed under the MIT License - see the LICENSE file for details.