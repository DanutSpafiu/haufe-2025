import streamlit as st
import ollama
import subprocess
import time
import re
import json
import yaml
import textwrap

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

# --- Run Code Review with LLM (UPDATED for Cost/Resource Tracking) ---
def run_code_review(code_content: str) -> dict:
    """Analyzes git diff using LLM with custom guidelines and tracks resource usage."""
    custom_guidelines = st.session_state.get('custom_guidelines', '')
    guidelines_block = f"\n\n**CUSTOM CODING GUIDELINES**:\n{custom_guidelines}\n" if custom_guidelines else ""

    SYSTEM_PROMPT = f"""
    You are an expert Senior Software Engineer specializing in highly concise, actionable, and structured code reviews.
    Analyze the provided git diff. Focus ONLY on the changes and their immediate context.

    **GUIDELINE AWARENESS CHECK**: Prioritize checking for violations of **PEP8** (especially naming conventions, maximum 79-character line length, and whitespace rules) and general readability standards.
    {guidelines_block}

    Your response MUST be in clear Markdown, except number 3) where the output should be displayed in the corresponding programming language markdown and follow this precise structure:

    1.  **Verdict and Effort Estimation**: A brief high-level summary. Must include an Effort Estimation (Low, Medium, or High) to apply suggested changes.
        * Example: 'Minor stylistic suggestions. Effort: Low.'

    2.  **Issues and Recommendations**: A numbered list of findings. Each point MUST address one or more of the following criteria:
        * Potential Bugs/Errors (High Priority)
        * Security Issues (High Priority)
        * **Style violations (e.g., PEP8 adherence, Google Style)** or readability issues.
        * Adherence to best practices (including Architecture or CI/CD impact).

    3.  **Automatic Fixes**: For one high-priority issue, provide an immediate fix in a code block. This fix should represent the replacement code, NOT a git patch. If no fixes are critical, state 'None provided.'
        *All code must be enclosed in a Markdown code block with the language identifier specified (e.g., ```python ... ```), with proper coloring and syntax.
        * Format for fix: Start the line with `[FIX_START]` and end the block with `[FIX_END]`.
        
    4.  **Documentation Suggestions**: List every file that needs an update (e.g., `README.md`, `docs/api.md`) followed by the exact markdown text to add/insert.  
        If nothing is required, write **exactly**: `Documentation Suggestions: None needed.`
    """

    user_content = f"Review this git diff:\n\n{code_content}"
    
    # COST MANAGEMENT: Track input size
    input_size_chars = len(SYSTEM_PROMPT) + len(user_content)

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': user_content},
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
        
        # COST MANAGEMENT: Track output size
        output_size_chars = len(review_text)

        return {
            'review': review_text, 
            'time': latency,
            'input_chars': input_size_chars,
            'output_chars': output_size_chars
        }
    except Exception as e:
        # Ensure we return the input size even on failure
        return {'review': f"LLM Review Failed: {e}", 'time': 0, 'input_chars': input_size_chars, 'output_chars': 0}

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

# Extract Auto-Fix Code
def extract_fixes(review_text: str) -> str:
    """Extract code between [FIX_START] and [FIX_END]."""
    match = re.search(r'\[FIX_START\]\s*```.*?(\w*)\n(.*?)\s*```\s*\[FIX_END\]', review_text, re.DOTALL)
    return match.group(2).strip() if match else ""

# Documentation Suggestions
def extract_doc_suggestions(review_text: str) -> list[dict]:
    """
    Pulls the **Documentation Suggestions** section from the LLM output.
    Returns a list of dicts: [{'file': 'README.md', 'content': '…'}, …]
    """
    pattern = r"(?i)Documentation\s+Suggestions\s*:\s*(.+?)(?=(\n\d+\.\s|\Z))"
    raw = re.search(pattern, review_text, re.DOTALL)
    if not raw:
        return []

    suggestions = []
    lines = raw.group(1).strip().splitlines()
    current_file = None
    current_block = []

    for line in lines:
        file_match = re.match(r"^\s*([-\w./]+)\s*[:\-]\s*(.*)", line)
        if file_match:
            if current_file:
                suggestions.append({"file": current_file, "content": "\n".join(current_block).strip()})
            current_file = file_match.group(1).strip()
            current_block = [file_match.group(2).strip()] if file_match.group(2) else []
        elif current_file and line.strip():
            current_block.append(line.strip())

    if current_file:
        suggestions.append({"file": current_file, "content": "\n".join(current_block).strip()})

    return suggestions

def main():
    st.set_page_config(page_title="AI Code Review", layout="wide")
    st.title("🤖 CodeGod")
    st.markdown("### Code Review with **Gemma 3** via Ollama")
    st.caption("Upload `.json` or `.yaml` to define your team's coding standards.")

    st.divider()

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
            st.rerun()

    if uploaded:
        guideline_text = load_guidelines(uploaded)
        if guideline_text:
            st.session_state.custom_guidelines = guideline_text
            st.success("Custom guidelines loaded!")

    diff_content = get_staged_changes()

    if not diff_content:
        st.info("No staged changes. Use `git add <file>` to stage.")
        st.text_area("Git Diff Preview", "# No changes staged", height=200, disabled=True)
    else:
        st.success("Staged changes detected. Ready for review.")
        with st.expander("View Staged Diff", expanded=False):
            st.code(diff_content, language='diff')

        if st.button("🚀Review Code", type="primary", use_container_width=True):
            with st.spinner(f"Reviewing with {LLM_MODEL}..."):
                review_data = run_code_review(diff_content)

            st.markdown("---")
            
            # COST MANAGEMENT: Display Resource Metrics (UPDATED)
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Review Time", f"{review_data['time']:.2f}s")
            
            with col2:
                # Estimate tokens: 1 token is roughly 4 characters (for English text)
                input_tokens = int(review_data['input_chars'] / 4) 
                st.metric("Prompt Size (est.)", f"{input_tokens:,} tokens")

            with col3:
                output_tokens = int(review_data['output_chars'] / 4)
                st.metric("Response Size (est.)", f"{output_tokens:,} tokens")
                
            with col4:
                st.metric("Total Characters", f"{(review_data['input_chars'] + review_data['output_chars']):,}")
                
            st.markdown("---")
            
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

                                # Extract added lines from diff
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

            # --- Documentation Suggestions Section ---
            doc_suggestions = extract_doc_suggestions(review_data['review'])
            if doc_suggestions:
                st.markdown("---")
                st.subheader("Documentation Suggestions")
                for idx, sug in enumerate(doc_suggestions, 1):
                    file_name = sug["file"]
                    content   = sug["content"]

                    with st.expander(f"{idx}. `{file_name}`", expanded=False):
                        st.markdown("**Suggested addition / update**")
                        preview = f"```markdown\n{content}\n```"
                        st.markdown(preview)

                        # One-click copy
                        copy_key = f"copy_doc_{idx}"
                        if st.button("Copy to Clipboard", key=copy_key):
                            st.code(content, language="markdown")
                            st.success("Copied! Paste it into the file manually or use the auto-PR button below.")

                        # Auto-PR for docs (optional)
                        if st.button("Create Docs PR", key=f"pr_doc_{idx}", help="Opens a PR that appends the suggestion"):
                            with st.spinner("Creating Documentation PR…"):
                                try:
                                    import apply_fix_to_github as gh
                                    pr = gh.create_pr_with_fix(
                                        repo=st.secrets.get("GITHUB_REPO", "your-username/your-repo"),
                                        branch=f"ai-doc-{int(time.time())}",
                                        file_path=file_name,
                                        old_code="",                     # we are *appending*
                                        new_code=content + "\n",
                                        commit_message=f"docs: update {file_name} (AI suggestion)",
                                        pr_title=f"Docs: AI-suggested update for `{file_name}`",
                                        pr_body=f"Automatically generated documentation update.\n\n**Suggested content**:\n```markdown\n{content}\n```",
                                        append=True
                                    )
                                    st.success(f"Docs PR created! [View]({pr['html_url']})")
                                except Exception as e:
                                    st.error(f"Docs PR failed: {e}")
            else:
                st.info("**Documentation Suggestions**: None needed.")

            st.markdown("---")
            st.caption("CI/CD: This app auto-deploys to Streamlit Cloud on push to `main`.")

if __name__ == "__main__":
    main()   
    #streamlit run .\app.py