import streamlit as st
import ollama
import subprocess
import time

# --- CONFIGURATION ---
LLM_MODEL = 'gemma3'  # The model you are currently downloading
OLLAMA_HOST = 'http://localhost:11434'

try:
    client = ollama.Client(host=OLLAMA_HOST)
except Exception as e:
    st.error(f"Error connecting to Ollama: Ensure the Ollama application is running. Details: {e}")
    st.stop()
    
def run_code_review(code_content: str) -> dict:
    """Analyzes code using the LLM and returns the structured response."""
    
    SYSTEM_PROMPT = f"""
    You are an expert Senior Software Engineer specializing in concise, actionable code reviews.
    Analyze the provided git diff. Focus ONLY on the changes and their context.
    
    CRITERIA:
    1. Potential Bugs/Errors.
    2. Security Issues.
    3. Style violations or readability issues.
    4. Adherence to best practices.
    
    Provide your response in clear Markdown. 
    1. Start with a brief, high-level **Verdict** (e.g., 'Minor Suggestions' or 'Approved').
    2. Provide a numbered list of issues.
    3. For high-priority issues, provide an automatic fix block using the format:
       <suggested code block>
    """

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f"Please review the following code changes (git diff):\n\n{code_content}"},
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
  
def get_staged_changes():
    """Fetches the content of staged changes using git diff."""
    try:
        # Use subprocess to run the git command
        result = subprocess.run(
            ['git', 'diff', '--staged'], 
            capture_output=True, 
            text=True, 
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return "" # Returns empty if no changes are staged
    except FileNotFoundError:
        st.error("Git command not found. Ensure Git is installed and in your PATH.")
        return ""
      
def main():
    st.title("🤖 AI-Powered Code Review Assistant")
    st.markdown("### Powered by Local LLM: **Gemma 3** (via Ollama)")
    st.divider()

    diff_content = get_staged_changes()

    if not diff_content:
        st.info("No staged changes found (`git diff --staged` is empty). Please stage a file to review.")
        st.text_area("Example: Code to Review (You can paste code here if the diff is empty):", 
                     value="# No changes staged...", height=200, disabled=True)
    else:
        st.success("✅ Found Staged Changes. Ready for Review.")
        st.code(diff_content, language='diff')

        if st.button("🚀 Run AI Code Review", type="primary"):
            with st.spinner("Analyzing code with Gemma 3..."):
                # Call the core logic
                review_data = run_code_review(diff_content)
                
            # Display Optimization/Cost Awareness (300 pts)
            st.metric(label="Review Time (Performance Optimization)", 
                      value=f"{review_data['time']:.2f} seconds")

            st.markdown("---")
            st.subheader("💡 LLM Review Feedback:")
            
            # Display Response Quality
            st.markdown(review_data['review'])
            
            # A simple implementation placeholder for Automatic Fixes (500 pts)
            if "[FIX_START]" in review_data['review']:
                st.info("Automatic fix suggestions detected in the review above!")
                st.button("✨ Simulate Applying Fixes (Placeholder)", disabled=True)

if __name__ == "__main__":
    main()