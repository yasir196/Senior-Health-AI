# Senior Health AI Local GUI

This is a simple local Streamlit control panel for the Senior Health AI production system.

The GUI does not run Codex automatically. It creates folders, lets you review/edit local files, and generates commands you can copy into Codex Desktop.

## Install

From the project root:

```powershell
pip install -r requirements.txt
```

## Run

```powershell
streamlit run app.py
```

Then open the local URL shown by Streamlit, usually:

```text
http://localhost:8501
```

## How To Use

1. Open the **Config** tab to review or edit `config.json`.
2. Use **Dashboard** to see all project folders and which required files are present.
3. Use **New Project** to enter a topic, create a project folder, and copy the Stage 1 Codex command.
4. Use **Commands** to generate copyable Codex commands for the selected project.
5. Use **Files** to view and edit Markdown files or preview CSV files.
6. There is no Titles stage. The exact **Anchor / Outlier Title** entered when creating the project is the immutable winning title used by every downstream stage.
7. Use **Thumbnail** to review thumbnail concepts and save your choice to `selected_thumbnail.txt`.
8. Use **Script** to view `06_final_script.md`, estimate word count, and read runtime metrics when present.
9. Use **Analytics** to inspect local analytics CSV or JSON files if present.

## Known Limitations

- The GUI does not call Codex directly.
- The winning title source is deterministic: `project.json.anchor_title`.
- CSV files are shown as tables and can be downloaded, but they are not edited in the GUI.
- Analytics charts are basic and depend on available CSV columns.
- The app is intended for local Windows use and reads files relative to the project root.

## Writer Workspace

Use **Writer Workspace** after **Prepare Opus Package**. Select a project, download `opus_writer_package.md`, write the script manually in Claude, and upload `.md` or `.txt`. The file is normalized to `06_final_script.md`; replacement creates a timestamped backup. Validation and runtime metrics are shown in the page, and Narrative QA stays disabled until validation passes.
