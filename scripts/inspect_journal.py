"""Print a PSD2Live authoring journal and test one obsolete-mesh cleanup."""

import argparse
import json

from layer_archive import load_project, mesh_delta_targets, plan_obsolete_mesh_removal, summarize_journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Saved .psd2live baseline")
    parser.add_argument("--check", help="Test MESH_ID:PARAMETER without writing")
    args = parser.parse_args()
    _, _, _, _, snapshot = load_project(args.project)
    journal = (snapshot.get("rigEdits") or {}).get("authoringJournal") or []
    result = {
        "events": summarize_journal(journal),
        "mesh_delta_targets": mesh_delta_targets(journal),
    }
    exit_code = 0
    if args.check:
        mesh_id, separator, parameter = args.check.partition(":")
        if not separator or not mesh_id or not parameter:
            raise ValueError("--check must be MESH_ID:PARAMETER")
        try:
            report = plan_obsolete_mesh_removal(snapshot, mesh_id, parameter)
            report.pop("indices", None)
            result["cleanup"] = {"accepted": True, **report}
        except ValueError as error:
            result["cleanup"] = {
                "accepted": False,
                "mesh": mesh_id,
                "parameter": parameter,
                "reason": str(error),
            }
            exit_code = 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
