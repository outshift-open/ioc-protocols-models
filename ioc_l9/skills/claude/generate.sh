#!/usr/bin/env python3
"""
Generate Claude SKILL_generated.md files using LLM

This script processes Claude skill folders by:
1. Copying SKILL_root.md to SKILL_generated.md in each folder
2. To skip LLM enhancement, use the --skip-llm flag
2. Optionally enhancing with LLM if environment variables are set
4. Uses generated JSON schema as part of LLM enhancement

IMPORTANT: This script NEVER modifies the original SKILL_root.md files.
All operations are read-only on source files and write-only to SKILL_generated.md.

The script is generic and can be used across different projects by customizing
the project_context configuration in the main() function.
"""
import json
import os
import sys
import argparse
from pathlib import Path

# OpenAI import is only needed for LLM functionality
openai = None
try:
    import openai
except ImportError:
    openai = None  # Will be checked later if LLM is actually needed

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load .env from current directory (skills/claude/)
    load_dotenv()
except ImportError:
    # python-dotenv not installed, user needs to source .env manually
    pass

def get_script_dir():
    """Get the directory where this script is located"""
    return Path(__file__).parent.absolute()


def load_schema(schema_path):
    """Load and validate JSON schema file"""
    try:
        with open(schema_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Schema file not found: {schema_path}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in schema file: {e}")
        return None

def create_prompt(schema_data, existing_skill_content, skill_name, project_context=None):
    """Create the prompt for LLM to generate SKILL_generated.md"""
    
    # Extract key info from schema for context (if schema is provided)
    if schema_data:
        title = schema_data.get("title", "Protocol")
        description = schema_data.get("description", "")
        properties = schema_data.get("properties", {})
        defs = schema_data.get("$defs", {})
        schema_context = f"""
JSON SCHEMA:
```json
{json.dumps(schema_data, indent=2)[:8000]}{" ..." if len(json.dumps(schema_data)) > 8000 else ""}\n```

SCHEMA CONTEXT:
- Protocol: {title}
- Description: {description}
- Properties: {list(properties.keys())}
- Definitions: {list(defs.keys())}"""
    else:
        schema_context = "No JSON schema provided - enhance based on existing skill content only."
    
    # Use project context if provided, otherwise use generic context
    if not project_context:
        project_context = {
            "name": "Protocol",
            "description": "protocol development and validation",
            "languages": ["Python", "Go"],
            "target_audience": "Developers"
        }
    
    prompt = f"""You are an expert technical writer creating documentation for AI assistants.

Generate a comprehensive Claude SKILL_generated.md file for the {skill_name} skill.

REQUIREMENTS:
1. Follow the exact structure and tone of the existing SKILL_root.md file
2. If schema is provided, extract message types, field names, and validation rules
3. Create realistic code examples using available language bindings
4. Include common mistakes and debugging tips
5. Reference appropriate file paths for the project structure
6. Focus on the {skill_name} skill functionality
7. Maintain consistency with existing skill documentation patterns

FORMAT REQUIREMENTS:
- Start with YAML frontmatter exactly as shown in SKILL_root.md (no markdown code blocks around it)
- The file must begin with raw YAML frontmatter like this:
  ---
  name: skill-name
  description: skill description
  ---
- Do NOT wrap the YAML in ```yaml or ```markdown blocks
- Follow the exact same section structure as the reference file

CONTEXT:
- Skill Name: {skill_name}
- Project: {project_context['name']}
- Purpose: {project_context['description']}
- Target Audience: {project_context['target_audience']}
- Available Languages: {', '.join(project_context['languages'])}

INSTRUCTIONS:
- Do not enhance the existing SKILL_root.md content with additional details
- Keep the same structure and sections as the original
- Add schema-specific information if available
- Provide practical examples and use cases
- Include troubleshooting and common pitfalls
- Ensure the skill is actionable for Claude to use effectively
- CRITICAL: Match the exact format of SKILL_root.md, especially the YAML frontmatter at the top

{schema_context}

EXISTING SKILL_root.md FOR REFERENCE:
{existing_skill_content[:3000]}

Generate a complete, professional SKILL_generated.md file that Claude can use to effectively assist developers. Enhance the existing content while maintaining the same structure and style."""

    return prompt

def call_llm(prompt, model, api_key, base_url=None, temperature=0.3, max_tokens=4000):
    """Call LLM API to generate SKILL_generated.md content"""
    
    # Configure OpenAI client
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    
    client = openai.OpenAI(**client_kwargs)
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert technical writer specializing in AI assistant documentation and protocol specifications."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"Error calling LLM API: {e}")
        return None

def check_env_variables():
    """Check if required environment variables and packages are present for LLM usage"""
    # Check for openai package
    if openai is None:
        print("Error: openai package not found. Install with: pip install openai")
        return False
    
    # Check for required environment variables
    required_vars = ["LLM_API_KEY"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set them in .env file or environment")
        print("See .env.example for reference")
        return False
    
    return True

def process_skill_folder(skill_folder, schema_data, use_llm=False, project_context=None):
    """Process a single skill folder - NEVER modifies original SKILL_root.md"""
    skill_name = skill_folder.name
    skill_root_path = skill_folder / "SKILL_root.md"
    skill_generated_path = skill_folder / "SKILL_generated.md"
    
    print(f"\nProcessing skill: {skill_name}")
    
    # Store original file hash to verify it's never modified
    original_hash = None
    if skill_root_path.exists():
        try:
            import hashlib
            original_content = skill_root_path.read_bytes()
            original_hash = hashlib.md5(original_content).hexdigest()
        except Exception:
            pass  # Hash verification is optional
    
    # Check if SKILL_root.md exists
    if not skill_root_path.exists():
        print(f"  Warning: SKILL_root.md not found in {skill_folder}")
        return False
    
    # Step 1: Copy SKILL_root.md to SKILL_generated.md (read-only operation on source)
    print(f"  Copying SKILL_root.md to SKILL_generated.md")
    try:
        # Ensure we never accidentally write to the source file
        if skill_root_path == skill_generated_path:
            print(f"  Error: Source and destination paths are the same!")
            return False
        
        # Read source file (read-only operation)
        skill_root_content = skill_root_path.read_text(encoding='utf-8')
        
        # Verify source file wasn't empty (sanity check)
        if not skill_root_content.strip():
            print(f"  Warning: SKILL_root.md appears to be empty")
        
        # Write to destination file only
        skill_generated_path.write_text(skill_root_content, encoding='utf-8')
        
        # Verify the copy was successful
        if not skill_generated_path.exists():
            print(f"  Error: Failed to create SKILL_generated.md")
            return False
            
    except Exception as e:
        print(f"  Error copying file: {e}")
        return False
    
    # Step 2: If LLM is available, enhance with LLM (schema is optional)
    if use_llm:
        print(f"  Enhancing with LLM...")
        
        # Get configuration from environment variables
        model = os.getenv("LLM_MODEL", "gpt-4o")
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
        max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4000"))
        
        # Create prompt and call LLM
        prompt = create_prompt(schema_data, skill_root_content, skill_name, project_context)
        enhanced_content = call_llm(prompt, model, api_key, base_url, temperature, max_tokens)
        
        if enhanced_content:
            # Double-check we're writing to the correct file (never the source)
            if skill_generated_path.name != "SKILL_generated.md":
                print(f"  Error: Attempting to write to wrong file: {skill_generated_path}")
                return False
            
            skill_generated_path.write_text(enhanced_content, encoding='utf-8')
            print(f"  ✓ Enhanced SKILL_generated.md with LLM")
        else:
            print(f"  Warning: LLM enhancement failed, keeping copied version")
    else:
        print(f"  Skipping LLM enhancement (environment variables not set)")
    
    # Final verification: Ensure original file was never modified
    if original_hash and skill_root_path.exists():
        try:
            import hashlib
            current_content = skill_root_path.read_bytes()
            current_hash = hashlib.md5(current_content).hexdigest()
            if current_hash != original_hash:
                print(f"  ERROR: Original SKILL_root.md was modified! This should never happen.")
                return False
        except Exception:
            pass  # Hash verification is optional
    
    print(f"  ✓ Generated: {skill_generated_path}")
    return True

def main():
    parser = argparse.ArgumentParser(description="Generate SKILL_generated.md files for Claude skills")
    parser.add_argument("--skill", help="Process only specific skill folder")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM enhancement even if env vars are set")
    
    args = parser.parse_args()
    
    script_dir = get_script_dir()
    print(f"Claude Skills Generator")
    print(f"Working directory: {script_dir}")
    
    # Check environment variables and skip-llm flag
    use_llm = check_env_variables() and not args.skip_llm
    
    # Project context configuration (can be customized per project)
    project_context = {
        "name": "IOC L9 Protocol",
        "description": "IOC L9 protocol development and validation",
        "languages": ["Python (Pydantic)", "Go (structs)"],
        "target_audience": "Developers working with IOC L9 Protocol"
    }
    
    # Load schema automatically when LLM is enabled
    schema_data = None
    if use_llm:
        # Hardcoded schema path relative to project root
        schema_path = script_dir.parent.parent / "spec" / "json_schema" / "l9.json"
        print(f"LLM enabled - loading schema: {schema_path}")
        if schema_path.exists():
            schema_data = load_schema(schema_path)
            if schema_data:
                print(f"✓ Loaded schema successfully")
            else:
                print(f"Error: Failed to load schema from {schema_path}")
                sys.exit(1)
        else:
            print(f"Error: Schema file not found: {schema_path}")
            print("Please ensure the schema file exists at the expected location")
            sys.exit(1)
    else:
        print("LLM disabled - will copy skills without schema enhancement")
    
    if use_llm:
        model = os.getenv("LLM_MODEL", "gpt-4o")
        print(f"LLM Model: {model}")
        print(f"Temperature: {os.getenv('LLM_TEMPERATURE', '0.3')}")
    
    # Find skill folders
    skill_folders = []
    if args.skill:
        # Process specific skill
        skill_folder = script_dir / args.skill
        if skill_folder.is_dir():
            skill_folders.append(skill_folder)
        else:
            print(f"Error: Skill folder not found: {skill_folder}")
            sys.exit(1)
    else:
        # Process all skill folders
        for item in script_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                skill_folders.append(item)
    
    if not skill_folders:
        print("No skill folders found")
        sys.exit(1)
    
    # Process each skill folder
    success_count = 0
    for skill_folder in skill_folders:
        if process_skill_folder(skill_folder, schema_data, use_llm, project_context):
            success_count += 1
    
    print(f"\nCompleted: {success_count}/{len(skill_folders)} skills processed successfully")
    
    if not use_llm:
        if args.skip_llm:
            print("\nNote: LLM enhancement was skipped due to --skip-llm flag")
        else:
            print("\nNote: To enable LLM enhancement, set environment variables as shown in .env.example")

if __name__ == "__main__":
    main()
