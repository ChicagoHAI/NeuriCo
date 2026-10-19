# Agentic robotics physical-safety evaluations: Roboharm, ASIMOV-2.0, ASIMOV-Agentic

- Slug: robotics-physical-safety-roboharm-asimov
- What it measures: Roboharm: refusal of physically harmful instructions by an agent controlling a bimanual robot via tool-call API (two harnesses). ASIMOV-2.0: hazard recognition in text/video from hospital injury reports; precision of triggering a safety intervention in a video stream; safety-instruction following under physical constraints. ASIMOV-Agentic: clarification-seeking vs over-refusal under uncertainty; detecting humans within a 1-meter safety zone.
- Metric: Refusal accuracy; recognition accuracy; intervention precision; clarification rate.
- Open-source: UNVERIFIED (ASIMOV benchmarks have public predecessors; not stated in report)
- Runnable on a 0.5B-7B open model: partially (text/video components).
- Source URL(s): https://storage.googleapis.com/deepmind-media/gemini/gemini_4_safety_report.pdf
- Fetched: 2026-10-19

## Description
"Gemini 4 led in nearly every evaluation when compared to Gemini Robotics ER2" (p.200); "safety behavior is highly sensitive to the actual harness used" (p.200). "These evaluations only cover high-level semantic safety reasoning and orchestration capabilities" (p.201). Numbers figure-only.

## Used by
- Used by: Google (Gemini 4 Argon Safety & Security Report, pp.199-201; labs/google/gemini-4-safety-report.md)
