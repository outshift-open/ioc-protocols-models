#!/bin/bash

# publish_skills.sh - Publish IOC L9 Protocol Skills
# 
# This script publishes generated skills to the artifacts folder with configurable
# platform and skill filtering support.
#
# Usage: ./skills/publish_skills.sh [platform] [version]
#   platform: claude|all (default: all)
#   version:  specific version or auto-detect from schema
#
# Examples:
#   ./skills/publish_skills.sh                    # Publish all platforms
#   ./skills/publish_skills.sh claude            # Publish Claude skills only
#   ./skills/publish_skills.sh claude 1.0.0      # Publish Claude skills with specific version

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IOC_L9_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$IOC_L9_DIR")"

# Logging functions
log_info() { echo "ℹ️  $1"; }
log_success() { echo "✅ $1"; }
log_error() { echo "❌ $1" >&2; }
log_step() { echo "🔄 $1"; }

# Configuration for skill filtering
# Add skills to exclude here (format: "platform/skill-name")
EXCLUDED_SKILLS=(
    # Example: "claude/experimental-skill"
    # Add skills to exclude from publishing here
)

# Check if a skill should be excluded
is_skill_excluded() {
    local platform="$1"
    local skill_name="$2"
    local skill_path="${platform}/${skill_name}"
    
    for excluded in "${EXCLUDED_SKILLS[@]+"${EXCLUDED_SKILLS[@]}"}"; do
        if [[ "$skill_path" == "$excluded" ]]; then
            return 0  # Skill is excluded
        fi
    done
    return 1  # Skill is not excluded
}

# Get version from schema or parameter
get_schema_version() {
    local current_dir=$(pwd)
    cd "$IOC_L9_DIR"
    local version=$(make -s print-version 2>/dev/null)
    cd "$current_dir"
    
    if [ -z "$version" ] || [ "$version" = "null" ]; then
        log_error "Version not found in schema file"
        exit 1
    fi
    
    echo "$version"
}

# Verify skills exist for platform
verify_skills_exist() {
    local platform="$1"
    
    if [ "$platform" = "all" ]; then
        # Check if any skills exist
        local found_skills=false
        for platform_dir in "$IOC_L9_DIR/skills"/*; do
            if [ -d "$platform_dir" ]; then
                local platform_name=$(basename "$platform_dir")
                if find "$platform_dir" -name "SKILL_generated.md" -type f | grep -q .; then
                    found_skills=true
                    break
                fi
            fi
        done
        
        if [ "$found_skills" = false ]; then
            log_error "No generated skills found in any platform"
            log_error "Please run 'make generate_skills' first to generate skills"
            exit 1
        fi
    else
        # Check specific platform
        if [ ! -d "$IOC_L9_DIR/skills/$platform" ]; then
            log_error "Platform directory not found: $IOC_L9_DIR/skills/$platform"
            exit 1
        fi
        
        if ! find "$IOC_L9_DIR/skills/$platform" -name "SKILL_generated.md" -type f | grep -q .; then
            log_error "No generated skills found for platform: $platform"
            log_error "Please run 'make generate_skills PLATFORM=$platform' first"
            exit 1
        fi
    fi
    
    log_success "Skills exist and ready for publishing"
}

# Publish skills for a specific platform
publish_platform_skills() {
    local platform="$1"
    local artifact_folder="$2"
    local published_count=0
    
    log_step "Publishing skills for platform: $platform"
    
    # Create platform directory
    mkdir -p "$artifact_folder/skills/$platform"
    
    # Find and copy all SKILL_generated.md files
    while IFS= read -r -d '' skill_file; do
        # Extract skill directory name
        local skill_dir=$(dirname "$skill_file")
        local skill_name=$(basename "$skill_dir")
        
        # Check if skill should be excluded
        if is_skill_excluded "$platform" "$skill_name"; then
            log_info "Excluding skill: $platform/$skill_name"
            continue
        fi
        
        # Create skill directory in artifacts
        local target_dir="$artifact_folder/skills/$platform/$skill_name"
        mkdir -p "$target_dir"
        
        # Copy the generated skill file and rename to SKILL.md
        cp "$skill_file" "$target_dir/SKILL.md"
        
        log_info "Published skill: $platform/$skill_name"
        ((published_count++))
        
    done < <(find "$IOC_L9_DIR/skills/$platform" -name "SKILL_generated.md" -type f -print0 2>/dev/null || true)
    
    if [ $published_count -eq 0 ]; then
        log_error "No skills found to publish for platform: $platform"
        return 1
    fi
    
    log_success "Published $published_count skills for platform: $platform"
    return 0
}

# Generate skills index.html
generate_skills_index() {
    local artifact_folder="$1"
    local version="$2"
    local git_tag="${3:-}"
    local git_commit="${4:-}"
    
    log_step "Generating skills index"
    
    local output_file="$artifact_folder/skills/index.html"
    
    # Start HTML generation
    cat > "$output_file" << EOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IOC L9 Protocol v$version - Skills Artifacts</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
        .header { border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px; }
        .platform { margin: 30px 0; padding: 20px; border: 1px solid #007acc; border-radius: 8px; background: #f0f8ff; }
        .skill { margin: 15px 0; padding: 12px; border: 1px solid #ddd; border-radius: 5px; background: #f9f9f9; }
        .version { color: #666; font-size: 0.9em; }
        .stats { margin: 20px 0; padding: 15px; border: 1px solid #28a745; border-radius: 5px; background: #f0fff0; }
        a { color: #0066cc; text-decoration: none; }
        a:hover { text-decoration: underline; }
        code { background: #f4f4f4; padding: 2px 4px; border-radius: 3px; font-family: monospace; }
        .skill-name { font-weight: bold; color: #333; }
        .platform-name { font-size: 1.2em; font-weight: bold; color: #007acc; }
        ul { margin: 10px 0; }
    </style>
</head>
<body>
    <div class="header">
        <h1>IOC L9 Protocol v$version - Skills</h1>
        <p class="version">Skills published: $(date -u +"%Y-%m-%d %H:%M:%S UTC")</p>
        <p class="version">Git Tag: $git_tag</p>
        <p class="version">Git Commit: $git_commit</p>
    </div>
    
    <h2>Published Skills</h2>
    
EOF

    # Generate platform sections
    local total_skills=0
    local total_platforms=0
    
    for platform_dir in "$artifact_folder/skills"/*; do
        if [ -d "$platform_dir" ] && [ "$(basename "$platform_dir")" != "index.html" ]; then
            local platform_name=$(basename "$platform_dir")
            ((total_platforms++))
            
            cat >> "$output_file" << EOF
    <div class="platform">
        <h3 class="platform-name">🤖 $platform_name</h3>
        <p>AI skills for the $platform_name platform</p>
        
EOF

            # List skills for this platform
            local platform_skills=0
            for skill_dir in "$platform_dir"/*; do
                if [ -d "$skill_dir" ]; then
                    local skill_name=$(basename "$skill_dir")
                    ((platform_skills++))
                    ((total_skills++))
                    
                    cat >> "$output_file" << EOF
        <div class="skill">
            <span class="skill-name">📝 $skill_name</span>
            <br>
            <a href="$platform_name/$skill_name/SKILL.md">View Skill Definition</a>
        </div>
EOF
                fi
            done
            
            cat >> "$output_file" << EOF
        <p><strong>Skills in this platform:</strong> $platform_skills</p>
    </div>
    
EOF
        fi
    done
    
    # Add statistics and footer
    cat >> "$output_file" << EOF
    <div class="stats">
        <h3>📊 Statistics</h3>
        <ul>
            <li><strong>Total Platforms:</strong> $total_platforms</li>
            <li><strong>Total Skills:</strong> $total_skills</li>
            <li><strong>Version:</strong> v$version</li>
        </ul>
    </div>
    
    <hr style="margin: 40px 0;">
    <footer>
        <p><strong>Repository:</strong> <a href="https://github.com/cisco-eti/ioc-protocols-models">https://github.com/cisco-eti/ioc-protocols-models</a></p>
        <p><strong>Issues:</strong> <a href="https://github.com/cisco-eti/ioc-protocols-models/issues">Report problems or request features</a></p>
        <p><strong>Skills Documentation:</strong> Each skill includes usage instructions and examples</p>
    </footer>
</body>
</html>
EOF

    log_success "Skills index generated: $output_file"
    log_info "📊 Total platforms: $total_platforms"
    log_info "📊 Total skills: $total_skills"
}

# Publish skills artifacts to configurable folder
publish_skills_artifacts() {
    local platform="$1"
    local version="$2"
    
    log_step "Publishing Skills Artifacts"
    
    # Get the artifact folder from Makefile
    local artifact_folder=$(cd "$IOC_L9_DIR" && make -s print-artifact-folder 2>/dev/null || echo "$PROJECT_ROOT/ioc_l9_artifacts")
    
    log_info "Publishing skills artifacts to: $artifact_folder/skills/"
    
    # Create skills directory
    mkdir -p "$artifact_folder/skills"
    
    # Get git information
    local git_tag=""
    local git_commit=""
    if command -v git >/dev/null 2>&1 && [ -d "$PROJECT_ROOT/.git" ]; then
        git_tag=$(cd "$PROJECT_ROOT" && git describe --tags --exact-match 2>/dev/null || echo "")
        git_commit=$(cd "$PROJECT_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "")
    fi
    
    # Publish skills based on platform parameter
    if [ "$platform" = "all" ]; then
        log_info "Publishing skills for all platforms..."
        
        local published_platforms=0
        for platform_dir in "$IOC_L9_DIR/skills"/*; do
            if [ -d "$platform_dir" ]; then
                local platform_name=$(basename "$platform_dir")
                
                # Skip if no generated skills exist
                if ! find "$platform_dir" -name "SKILL_generated.md" -type f | grep -q .; then
                    log_info "No generated skills found for platform: $platform_name (skipping)"
                    continue
                fi
                
                if publish_platform_skills "$platform_name" "$artifact_folder"; then
                    ((published_platforms++))
                fi
            fi
        done
        
        if [ $published_platforms -eq 0 ]; then
            log_error "No skills were published for any platform"
            exit 1
        fi
        
        log_success "Published skills for $published_platforms platforms"
    else
        # Publish specific platform
        if ! publish_platform_skills "$platform" "$artifact_folder"; then
            exit 1
        fi
    fi
    
    # Generate index.html
    generate_skills_index "$artifact_folder" "$version" "$git_tag" "$git_commit"
    
    log_success "Skills artifacts published to: $artifact_folder/skills/"
    log_info "✅ Skills index: index.html"
    
    # List published artifacts
    if [ "$platform" = "all" ]; then
        for platform_dir in "$artifact_folder/skills"/*; do
            if [ -d "$platform_dir" ] && [ "$(basename "$platform_dir")" != "index.html" ]; then
                local platform_name=$(basename "$platform_dir")
                local skill_count=$(find "$platform_dir" -name "SKILL.md" -type f | wc -l)
                log_info "✅ Platform $platform_name: $skill_count skills"
            fi
        done
    else
        local skill_count=$(find "$artifact_folder/skills/$platform" -name "SKILL.md" -type f | wc -l)
        log_info "✅ Platform $platform: $skill_count skills"
    fi
}

# Main function
main() {
    local platform="${1:-all}"
    local version="${2:-}"
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h)
                echo "Usage: $0 [platform] [version]"
                echo ""
                echo "Publishes IOC L9 Protocol skills to artifacts folder."
                echo "Uses the artifact folder configured in the Makefile (ARTIFACT_PUBLISH_FOLDER)."
                echo ""
                echo "Prerequisites:"
                echo "  Skills must be pre-generated using 'make generate_skills'"
                echo ""
                echo "Parameters:"
                echo "  platform                Platform to publish (claude|all, default: all)"
                echo "  version                 Version to use (default: auto-detect from schema)"
                echo ""
                echo "Options:"
                echo "  --help, -h              Show this help message"
                echo ""
                echo "Published artifacts:"
                echo "  - skills/{platform}/{skill}/SKILL.md    Individual skill definitions"
                echo "  - skills/index.html                      Skills index page"
                echo ""
                echo "Configuration:"
                echo "  Output location is controlled by ARTIFACT_PUBLISH_FOLDER in Makefile"
                echo "  Skill exclusions can be configured in EXCLUDED_SKILLS array"
                echo ""
                echo "Examples:"
                echo "  $0                      # Publish all platforms"
                echo "  $0 claude              # Publish Claude skills only"
                echo "  $0 claude 1.0.0        # Publish Claude skills with specific version"
                exit 0
                ;;
            *)
                # First unknown argument is platform, second is version
                if [ -z "${platform_set:-}" ]; then
                    platform="$1"
                    platform_set=true
                elif [ -z "$version" ]; then
                    version="$1"
                else
                    log_error "Unknown option: $1"
                    echo "Use --help for usage information"
                    exit 1
                fi
                ;;
        esac
        shift
    done
    
    # Get version if not provided
    if [ -z "$version" ]; then
        version=$(get_schema_version)
    fi
    
    log_info "Publishing IOC L9 Protocol Skills v$version"
    log_info "Platform: $platform"
    
    # Verify skills exist
    verify_skills_exist "$platform"
    
    # Publish skills artifacts
    publish_skills_artifacts "$platform" "$version"
    
    log_success "Skills publishing completed successfully!"
}

# Run main function with all arguments
main "$@"
