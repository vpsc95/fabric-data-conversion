import base64
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "conversion-platform" / "engine"))
from configure import validate
from deploy_reports import definition_parts
from generate_sample import generate
from convplat.reshape import run_reshape
from convplat.specs import ClientSpecs


def settings():
    config = json.loads((ROOT / "deployment.example.json").read_text(encoding="utf-8"))
    config["tenant_id"] = "11111111-1111-4111-8111-111111111111"
    config["foundry"].update(endpoint="https://example.cognitiveservices.azure.com/", region="canadaeast")
    for profile in ("mvp", "full"):
        config[profile].update(
            workspace_id="22222222-2222-4222-8222-222222222222",
            lakehouse_id="33333333-3333-4333-8333-333333333333",
            sql_database_id="44444444-4444-4444-8444-444444444444",
            sql_server="example.database.fabric.microsoft.com",
            sql_database_name="Demo")
    return config


class ReleaseTests(unittest.TestCase):
    def test_templates_need_recipient_configuration(self):
        template = json.loads((ROOT / "deployment.example.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            validate(template, "mvp")
        self.assertEqual(validate(settings(), "mvp")["sql_database_name"], "Demo")

    def test_no_tokens_or_global_endpoint_configuration(self):
        config = settings()
        config["foundry"]["endpoint"] = "https://example.cognitiveservices.azure.com/?api_key=not-allowed"
        with self.assertRaises(ValueError):
            validate(config, "mvp")
        config = settings()
        config["foundry"]["deployment_type"] = "GlobalStandard"
        with self.assertRaises(ValueError):
            validate(config, "full")

    def test_both_models_and_reports_are_deployable_definitions(self):
        for profile, prefix, directory in [
            ("mvp", "ConversionMVP", "conversion-mvp"),
            ("full", "ConversionRun", "conversion-platform"),
        ]:
            ws = validate(settings(), profile)
            base = ROOT / directory / "powerbi"
            parts = definition_parts(base / f"{prefix}.SemanticModel", ws)
            self.assertGreater(len(parts), 5)
            expressions = next(p for p in parts if p["path"] == "definition/expressions.tmdl")
            self.assertIn(ws["workspace_id"], base64.b64decode(expressions["payload"]).decode())
            model = "55555555-5555-4555-8555-555555555555"
            parts = definition_parts(base / f"{prefix}.Report", ws, model)
            pbir = next(p for p in parts if p["path"] == "definition.pbir")
            binding = json.loads(base64.b64decode(pbir["payload"]))
            self.assertEqual(binding["datasetReference"]["byConnection"]["connectionString"], f"semanticmodelid={model}")
            self.assertFalse(any(".pbi" in p["path"].split("/") for p in parts))

    def test_notebook_and_pipeline_placeholders_resolve(self):
        for profile, directory in (("mvp", "conversion-mvp"), ("full", "conversion-platform")):
            ws = validate(settings(), profile)
            values = {**ws, **{"foundry_" + k: v for k, v in ws["foundry"].items()}}
            fabric = ROOT / directory / "fabric"
            notebooks = list(fabric.glob("*.Notebook"))
            self.assertEqual(len(notebooks), 4 if profile == "mvp" else 10)
            values.update({n.stem: "66666666-6666-4666-8666-666666666666" for n in notebooks})
            for file in [*(n / "notebook-content.py" for n in notebooks), *fabric.glob("*.DataPipeline/pipeline-content.json")]:
                source = file.read_text(encoding="utf-8")
                for key, value in values.items():
                    if isinstance(value, str):
                        source = source.replace("{{" + key + "}}", value)
                self.assertFalse(re.findall(r"\{\{[^}]+\}\}", source), str(file))
                if file.suffix == ".py":
                    compile(source, str(file), "exec")
                else:
                    json.loads(source)

    def test_synthetic_schema_and_lineage(self):
        with tempfile.TemporaryDirectory(prefix="conversion-synthetic-") as tmp:
            output = Path(tmp)
            generate(output)
            for take in ("go-live", "sim-take2"):
                specs = ClientSpecs(ROOT / "conversion-platform" / "clients" / "sample", take)
                reshapes = specs.file_reshapes(output / take)
                self.assertEqual(len(reshapes), 5)
                sizes = {}
                for spec in reshapes:
                    result = run_reshape(spec, output / take)
                    sizes[result.target] = len(result.silver_rows)
                    self.assertEqual(len(result.silver_rows), len(result.silver_row_numbers))
                self.assertEqual(sizes, {"silver.customers": 10, "silver.services": 10,
                                        "silver.balances": 10, "silver.deposits": 10, "silver.reads": 20})

    def test_actual_notebook_importers_render_new_environment(self):
        original_read = Path.read_text
        for profile, relative in (("mvp", "conversion-mvp/deploy.py"),
                                  ("full", "conversion-platform/fabric/deploy.py")):
            ws = validate(settings(), profile)

            def read(path, *args, **kwargs):
                return json.dumps(ws) if path.name == "workspace.json" else original_read(path, *args, **kwargs)

            spec = importlib.util.spec_from_file_location("release_deploy_" + profile, ROOT / relative)
            module = importlib.util.module_from_spec(spec)
            with patch.object(Path, "read_text", read):
                spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as tmp, patch.object(module, "fab", return_value="77777777-7777-4777-8777-777777777777"):
                stage = Path(tmp)
                if profile == "mvp":
                    module.STAGE = stage
                    ids = module.import_notebooks()
                    module.import_pipelines(ids)
                else:
                    with patch.object(Path, "home", return_value=stage):
                        ids = module.import_notebooks()
                        module.import_pipelines(ids)
                    for source, _ in module.bundle_files():
                        self.assertTrue(source.exists() or source.name == "workspace.json", str(source))
                rendered = list(stage.rglob("notebook-content.py"))
                self.assertEqual(len(rendered), 4 if profile == "mvp" else 10)
                for file in rendered:
                    text = file.read_text(encoding="utf-8")
                    self.assertNotIn("{{", text)
                    self.assertIn("requirements-fabric.txt", text)
                    compile(text, str(file), "exec")
                for file in stage.rglob("pipeline-content.json"):
                    text = file.read_text(encoding="utf-8")
                    self.assertNotIn("{{", text)
                    json.loads(text)


if __name__ == "__main__":
    unittest.main()
