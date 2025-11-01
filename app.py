import streamlit as st
import ollama
import subprocess
import time
import re
import json
import yaml

# --- CONFIGURATION ---
LLM_MODEL = 'gemma3'  # Change to your model (e.g., 'codellama', 'gemma2:2b')
OLLAMA_HOST = 'http://localhost:11434'

# --- Initialize Ollama Client ---
try:
    client = ollama.Client(host=OLLAMA_HOST)
    # Test connection
    client.list()
except Exception as e:
    st.error(f"Error connecting to Ollama: Ensure Ollama is running. Details: {e}")
    st.info("Start Ollama with: `ollama serve`")
    st.stop()

# --- Load Custom Guidelines ---
def load_guidelines(uploaded_file) -> str:
    """Load custom coding guidelines from JSON/YAML. Returns formatted string."""
    if uploaded_file is None:
        default = """
        # Default Coding Guidelines
        - Follow PEP 8 naming conventions (snake_case for variables/functions, CamelCase for classes).
        - Keep lines ≤ 79 characters.
        - Use 4-space indentation.
        - Add docstrings to every public function/class.
        - Avoid wildcard imports (`from module import *`).
        """
        return default.strip()

    try:
        content = uploaded_file.read().decode("utf-8")
        filename = uploaded_file.name.lower()

        if filename.endswith('.json'):
            data = json.loads(content)
        elif filename.endswith(('.yaml', '.yml')):
            data = yaml.safe_load(content)
        else:
            st.warning("Unsupported file type. Use .json, .yaml, or .yml")
            return ""

        if isinstance(data, str):
            return data.strip()
        elif isinstance(data, list):
            return "\n".join(f"- {rule}".strip() for rule in data if rule)
        else:
            st.warning("File must contain a string or list of rules.")
            return ""

    except Exception as e:
        st.error(f"Failed to parse guidelines: {e}")
        return ""

# --- Run Code Review with LLM ---
def run_code_review(code_content: str) -> dict:
    """Analyzes git diff using LLM with custom guidelines."""
    custom_guidelines = st.session_state.get('custom_guidelines', '')
    guidelines_block = f"\n\n**CUSTOM CODING GUIDELINES**:\n{custom_guidelines}\n" if custom_guidelines else ""

    SYSTEM_PROMPT = f"""
    You are an expert Senior Software Engineer specializing in highly concise, actionable, and structured code reviews.
    Analyze the provided git diff. Focus ONLY on the changes and their immediate context.

    **GUIDELINE AWARENESS CHECK**: Prioritize checking for violations of **PEP8** (especially naming conventions, maximum 79-character line length, and whitespace rules) and general readability standards.
    {guidelines_block}

    Your response MUST be in clear Markdown and follow this precise structure:

    1.  **Verdict and Effort Estimation**: A brief high-level summary. Must include an Effort Estimation (Low, Medium, or High) to apply suggested changes.
        * Example: 'Minor stylistic suggestions. Effort: Low.'

    2.  **Issues and Recommendations**: A numbered list of findings. Each point MUST address one or more of the following criteria:
        * Potential Bugs/Errors (High Priority)
        * Security Issues (High Priority)
        * **Style violations (e.g., PEP8 adherence, Google Style)** or readability issues.
        * Adherence to best practices (including Architecture or CI/CD impact).

    3.  **Automatic Fixes**: For one high-priority issue, provide an immediate fix in a code block. This fix should represent the replacement code, NOT a git patch. If no fixes are critical, state 'None provided.'
        * Format for fix: Start the line with `[FIX_START]` and end the block with `[FIX_END]`.
        
    4.  **Documentation Suggestions**: Briefly recommend any necessary updates to related documentation (README, API docs, etc.) or state 'None needed.'
    """

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f"Review this git diff:\n\n{code_content}"},
    ]

    start_time = time.time()
    try:
        response = client.chat(
            model=LLM_MODEL,
            messages=messages,
            options={'temperature': 0.15, 'seed': 42}
        )
        latency = time.time() - start_time
        review_text = response['message']['content']
        return {'review': review_text, 'time': latency}
    except Exception as e:
        return {'review': f"LLM Review Failed: {e}", 'time': 0}

# --- Get Staged Git Changes ---
def get_staged_changes() -> str:
    """Fetches `git diff --staged` output."""
    try:
        result = subprocess.run(
            ['git', 'diff', '--staged'],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return ""
    except FileNotFoundError:
        st.error("Git not found. Install Git and ensure it's in PATH.")
        return ""

# --- Extract Auto-Fix Code ---
def extract_fixes(review_text: str) -> str:
    """Extract code between [FIX_START] and [FIX_END]."""
    match = re.search(r'\[FIX_START\]\s*```.*?(\w*)\n(.*?)\s*```\s*\[FIX_END\]', review_text, re.DOTALL)
    return match.group(2).strip() if match else ""

# --- Main App ---
def main():
    st.set_page_config(page_title="AI Code Review", layout="wide")
    st.title("AI-Powered Code Review Assistant")
    st.markdown("### Incremental Review with **Gemma 3** via Ollama + **Custom Guidelines**")
    st.caption("Upload `.json` or `.yaml` to define your team's coding standards.")

    st.divider()

    # --- Guideline Import UI ---
    col_guide, col_reset = st.columns([4, 1])
    with col_guide:
        uploaded = st.file_uploader(
            "Custom Guidelines (optional)",
            type=["json", "yaml", "yml"],
            help="JSON: string or list; YAML: same. Example: ['Use type hints', 'Max line: 88']"
        )
    with col_reset:
        if st.button("Reset", help="Clear custom guidelines"):
            keys_to_clear = [k for k in st.session_state.keys() if k.startswith('custom_guidelines')]
            for k in keys_to_clear:
                del st.session_state[k]
            st.success("Guidelines reset to default.")
            st.experimental_rerun()

    # Load and store guidelines
    if uploaded:
        guideline_text = load_guidelines(uploaded)
        if guideline_text:
            st.session_state.custom_guidelines = guideline_text
            st.success("Custom guidelines loaded!")

    # --- Get Git Diff ---
    diff_content = get_staged_changes()

    if not diff_content:
        st.info("No staged changes. Use `git add <file>` to stage.")
        st.text_area("Git Diff Preview", "# No changes staged", height=200, disabled=True)
    else:
        st.success("Staged changes detected. Ready for review.")
        with st.expander("View Staged Diff", expanded=False):
            st.code(diff_content, language='diff')

        if st.button("🚀 Review Code", type="primary", use_container_width=True):
            with st.spinner(f"Reviewing with {LLM_MODEL}..."):
                review_data = run_code_review(diff_content)

            st.markdown("---")
            col1, col2 = st.columns([1, 3])

            with col1:
                st.metric("Review Time", f"{review_data['time']:.2f}s")

            with col2:
                st.subheader("LLM Review")
                clean_review = review_data['review'].replace('[FIX_START]', '').replace('[FIX_END]', '')
                st.markdown(clean_review)

            # --- Auto-Fix Section ---
            fix_code = extract_fixes(review_data['review'])
            if fix_code:
                st.markdown("---")
                if 'show_fix' not in st.session_state:
                    st.session_state.show_fix = False

                col_apply, col_guide = st.columns([1, 1])
                with col_apply:
                    if st.button("Apply to GitHub (Auto-PR)", type="success", use_container_width=True):
                        with st.spinner("Creating PR on GitHub..."):
                            try:
                                import apply_fix_to_github as gh
                                import inspect
                                import textwrap

                                # Extract the original code block from diff (simplified)
                                diff_lines = diff_content.strip().split('\n')
                                added_lines = [line[1:] for line in diff_lines if line.startswith('+') and not line.startswith('+++')]
                                old_code = textwrap.dedent(''.join(added_lines)).strip()

                                if not old_code:
                                    st.error("Could not detect modified code block.")
                                else:
                                    pr = gh.create_pr_with_fix(
                                        repo=st.secrets.get("GITHUB_REPO", "your-username/your-repo"),
                                        branch=f"ai-fix-{int(time.time())}",
                                        file_path="app.py",
                                        old_code=old_code,
                                        new_code=fix_code,
                                        commit_message="fix: AI-suggested code improvement",
                                        pr_title="AI Fix: Apply LLM suggestion",
                                        pr_body=f"Automatically applied fix from AI code review.\n\n**Original diff**:\n```diff\n{diff_content}\n```",
                                    )
                                    pr_url = pr["html_url"]
                                    st.success(f"PR created! [View on GitHub]({pr_url})")
                            except Exception as e:
                                st.error(f"Failed to create PR: {e}")

                with col_guide:
                    if st.button("Show Manual Guide"):
                        st.session_state.show_fix = not st.session_state.show_fix

                if st.session_state.show_fix:
                    with st.expander("Manual Fix Guide", expanded=True):
                        st.warning("Direct edits disabled. Use steps below.")
                        st.subheader("1. Suggested Fix")
                        st.code(fix_code, language='python')
                        st.subheader("2. Apply Manually")
                        st.code("""git add app.py
                        git commit -m "fix: AI suggestion"
                        git push origin HEAD""", language="bash")
            else:
                st.info("No critical auto-fixes suggested.")

            st.markdown("---")
            st.caption("CI/CD: This app auto-deploys to Streamlit Cloud on push to `main`.")

if __name__ == "__main__":
    main()