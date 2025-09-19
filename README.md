# Flask App with Entra ID (Azure AD) SSO Authentication

## 📋 Prerequisites

### System Requirements
- Python **3.9+** (recommended: 3.9 or 3.10)  
- pip (latest version)  
- Git (optional, for source code management)  
- A browser (Edge, Chrome, Firefox, etc.)  

---

## 🔑 Azure Entra ID (Azure AD) Setup

### Register an Application
1. Go to **Azure Portal → Entra ID → App registrations → New registration**.  
2. Give it a name (e.g., `Flask-DevOps-App`).  
3. Supported account type: **Single tenant** (or multi-tenant if required).  
4. Redirect URI:  http://localhost:8000/getAToken

*(must match `REDIRECT_PATH` in `app.py`)*

### Configure Secrets
- Go to **Certificates & Secrets → New Client Secret**.  
- Copy the **secret value** (cannot be retrieved later).  

### API Permissions
- Add **Microsoft Graph → Delegated → User.Read**.  
- Grant **admin consent**.  

### Collect IDs
- Application (client) ID → `AZURE_CLIENT_ID`  
- Directory (tenant) ID → `AZURE_TENANT_ID`  
- Client secret → `AZURE_CLIENT_SECRET`  

---

## ⚙️ Azure DevOps Setup

1. Generate a **Personal Access Token (PAT)** with at least:
- `User.Read`
- `User Entitlements` (Graph scope in Azure DevOps REST API)  
2. Get the list of organizations where you want to check entitlements.  

---

## 💻 Local Development Setup (VSCode)

```powershell
# Create virtual environment
python -m venv .venv

# Environment variables
$env:AZURE_CLIENT_ID=""
$env:AZURE_CLIENT_SECRET=""
$env:AZURE_TENANT_ID=""
$env:FLASK_SECRET_KEY="MyTestSecret19896"

$env:FLASK_APP="local.app.py"
$env:FLASK_ENV="development"

$env:AZURE_DEVOPS_PAT=""    # For all organizations that will be used
$env:AZDO_ORGS="org1,org2"

# Activate venv
.\.venv\Scripts\Activate

# Run the app
python local.app.py
```
## 🔐 Authentication Flow

Click Login → Redirect to Microsoft Entra login page.
After login → Redirect to /getAToken.
Token acquired & stored in session.
Dashboard shows user entitlements across Azure DevOps orgs.

python local.app.py

## ✅ Testing the Authentication Flow
Login Test

Go to /login → Sign in with Entra ID credentials.

Verify session stores user and graph_token.

Graph API Test

Access /me/photo → Should return user’s profile photo (or blank).

Azure DevOps Test

Ensure AZURE_DEVOPS_PAT and AZDO_ORGS are set.

After login, orgs and entitlements should display on the dashboard.

Try /enable_access → Should patch user’s license if Stakeholder.

Logout Test

Visit /logout → Session clears → Redirect to Entra logout.

## 🚀 Production Notes

Use Gunicorn for production:

gunicorn -w 4 -b 0.0.0.0:8000 app:app

Store secrets in Azure Key Vault or environment variables, not in code.

Configure HTTPS in production (Flask dev server is HTTP only).

Use azurewebapp.app.py for cloud deployments.
