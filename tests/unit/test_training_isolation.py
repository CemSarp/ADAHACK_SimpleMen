"""Each comparison owns its reports, even when another session starts training."""

from src.dashboard import explain, trainer


def test_comparisons_keep_separate_output_directories(monkeypatch, tmp_path):
    class Process:
        stdout = ()

        def wait(self):
            return 0

    commands = []

    def start(command, **kwargs):
        commands.append(command)
        return Process()

    monkeypatch.setattr(trainer, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(trainer.subprocess, "Popen", start)
    first = trainer.TrainingJob(["SeasonalNaive"])
    report = first.output_dir / "emissions" / "summary.json"
    report.parent.mkdir()
    report.write_text('{"best_model": "SeasonalNaive"}')
    second = trainer.TrainingJob(["RandomForest"])
    assert first.output_dir != second.output_dir
    assert report.exists()
    assert commands[0][-1] == str(first.output_dir)
    assert commands[1][-1] == str(second.output_dir)
    assert explain._summaries(first)["emissions"]["best_model"] == "SeasonalNaive"
    assert explain._summaries(second) == {}
