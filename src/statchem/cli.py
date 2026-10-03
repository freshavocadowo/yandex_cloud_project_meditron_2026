import json
from pathlib import Path

import typer

from .contract import Output, SCHEMA
from .pipeline import batch, write_json
from .settings import Settings

app = typer.Typer(help="Извлечение 50 признаков из синтетических эпикризов.")


@app.command()
def run(input_dir: Path = typer.Option(Path("participant-kit-realistic-v2-100/documents"), "--input"),
        output: Path = Path("result"), reports: Path = Path("reports"),
        mode: str = "rules", limit: int | None = typer.Option(None, min=1),
        ner: bool = typer.Option(True, "--ner/--no-ner")):
    """Process a directory; cloud requests only in explicit yandex mode."""
    if mode not in {"rules", "yandex"}:
        raise typer.BadParameter("mode must be rules or yandex")
    settings = Settings()
    settings.use_ner = ner
    try:
        summary = batch(input_dir, output, reports, settings, mode, limit)
    except Exception as exc:
        # Neither API error messages nor arbitrary paths belong in logs.
        typer.echo(f"Запуск невозможен: {type(exc).__name__}; проверьте каталог, режим и config/.env.")
        raise typer.Exit(2)
    typer.echo(json.dumps({k: v for k, v in summary.items() if k != "items"}, ensure_ascii=False, indent=2))
    if summary["failed"]:
        raise typer.Exit(1)


@app.command()
def validate(directory: Path = Path("result")):
    """Validate all exported files independently."""
    from jsonschema import Draft202012Validator
    from .contract import assemble
    paths = list(directory.glob("*.json"))
    errors = 0
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            Output.model_validate(value)
            Draft202012Validator(SCHEMA).validate(value)
            assemble({f: v for group in value.values() for f, v in group.items()})
        except Exception:
            errors += 1
    typer.echo(f"Файлов: {len(paths)}; ошибок: {errors}")
    if errors or not paths:
        raise typer.Exit(1)


@app.command()
def schema(output: Path = Path("config/output.schema.json")):
    write_json(output, SCHEMA)
    typer.echo("Схема сохранена.")


@app.command()
def evaluate(gold: Path = typer.Option(..., "--gold"), predictions: Path = Path("result"),
             report: Path = Path("reports/evaluation.json")):
    """Compare outputs against separately prepared reference JSON files."""
    from .evaluation import evaluate as score
    try:
        result = score(gold, predictions)
    except Exception as exc:
        typer.echo(f"Оценка невозможна: {type(exc).__name__}.")
        raise typer.Exit(2)
    write_json(report, result)
    typer.echo(f"Документов: {result['documents']}; совпало полей: {result['matched_fields']}/{result['total_fields']}")


@app.command()
def check_api():
    """Small connectivity/model check; sends no medical documents."""
    from openai import OpenAI
    try:
        s = Settings()
        s.require_cloud()
        client = OpenAI(api_key=s.api_key.get_secret_value(), project=s.folder_id,
                        base_url="https://ai.api.cloud.yandex.net/v1", timeout=s.timeout_seconds, max_retries=2)
        response = client.chat.completions.create(model=s.model_uri, messages=[{"role": "user", "content": 'Верни JSON {"ok":true}'}], max_tokens=30,
            response_format={"type": "json_schema", "json_schema": {"name": "health", "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}}})
        if json.loads(response.choices[0].message.content) != {"ok": True}:
            raise ValueError("unexpected_response")
    except Exception as exc:
        typer.echo(f"API не проверен: {type(exc).__name__}. Проверьте config/.env, права и доступ к модели.")
        raise typer.Exit(2)
    typer.echo("Yandex API и структурированный ответ доступны.")
