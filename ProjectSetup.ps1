# Go to your project folder
cd "C:\echomediaai\M365RoadMap"

# Initialize a new Git repository (creates .git)
git init

# (Optional) Set your global identity if you haven't before
git config --global user.name "Shannon Bray"
git config --global user.email "shannonbraync@outlook.com"

# Create a .gitignore to avoid committing temp files (example combines Node + Python)
@"
# OS
Thumbs.db
.DS_Store

# Node
node_modules/
.npm-cache/
dist/
.env

# Python
.venv/
__pycache__/
*.pyc
.env*

# IDE
.vscode/
.idea/
"@ | Out-File -Encoding utf8 .gitignore

# Stage and commit everything
git add .
git commit -m "Initial commit"