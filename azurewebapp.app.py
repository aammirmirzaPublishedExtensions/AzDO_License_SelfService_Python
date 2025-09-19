import os
import io
import base64
import json
import subprocess
from flask import Flask, redirect, url_for, session, render_template, request, send_file, flash
from msal import ConfidentialClientApplication
import requests
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Honor Azure's reverse-proxy headers (X-Forwarded-Proto/Host)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config['PREFERRED_URL_SCHEME'] = 'https'

# Entra ID / MSAL config
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
TENANT_ID = os.getenv("AZURE_TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_PATH = "/getAToken"
# Graph only; we’ll use PAT for Azure DevOps
SCOPES = ["User.Read"]

# Azure DevOps config
AZURE_DEVOPS_PAT = os.getenv("AZURE_DEVOPS_PAT", "")
AZDO_ORGS = [o.strip() for o in os.getenv("AZDO_ORGS", "").split(",") if o.strip()]

if not CLIENT_ID or not CLIENT_SECRET or not TENANT_ID:
    raise RuntimeError("AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID are required")
if not AZURE_DEVOPS_PAT:
    print("Warning: AZURE_DEVOPS_PAT not set. Azure DevOps actions will not work.")
if not AZDO_ORGS:
    print("Warning: AZDO_ORGS not set. No organizations will be queried.")

msal_app = ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

def _ado_auth():
    # Basic auth with PAT: username can be empty; requests needs something
    return ("", AZURE_DEVOPS_PAT)

def _get_entitlements_for_org(org, email):
    """Return tuple (record, raw_list) where record matches the email, raw_list is all entitlements."""
    url = f"https://vsaex.dev.azure.com/{org}/_apis/userentitlements?top=10000&api-version=7.1-preview.3"
    r = requests.get(url, auth=_ado_auth())
    if r.status_code != 200:
        return None, []
    data = r.json()
    items = data.get("members") or data.get("value") or []
    # Match by mailAddress or principalName, case-insensitive
    email_lower = (email or "").lower()
    record = next((m for m in items
                   if (m.get("user", {}).get("mailAddress", "").lower() == email_lower) or
                      (m.get("user", {}).get("principalName", "").lower() == email_lower)), None)
    return record, items

def _license_str_from_entitlement(ent):
    al = (ent or {}).get("accessLevel") or {}
    # accountLicenseType: stakeholder | express (Basic) | advanced (VS/VSPro) | etc
    typ = (al.get("accountLicenseType") or "").lower()
    if typ == "express":
        return "Basic"
    if typ == "stakeholder":
        return "Stakeholder"
    return al.get("licenseDisplayName") or typ or "Unknown"

def _set_basic_for_user(org, entitlement_id):
    url = f"https://vsaex.dev.azure.com/{org}/_apis/userentitlements/{entitlement_id}?api-version=7.1-preview.3"
    patch_ops = [
    {
        "from": "",
        "op": "replace",
        "path": "/accessLevel",
        "value": {
            "accountLicenseType": "express",  # or "basic", etc.
            "licensingSource": "account"
        }
    }
]
    # Note: This will change the access level to Stakeholder; adjust as needed
    r = requests.patch(
        url,
        data=json.dumps(patch_ops),
        headers={"Content-Type": "application/json-patch+json"},
        auth=_ado_auth(),
    )
    return r.status_code in (200, 201), r.text


@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    user = session["user"]
    # Build org access list
    org_rows = []
    for org in AZDO_ORGS:
        ent, _ = _get_entitlements_for_org(org, user["upn"])
        if ent:
            access = _license_str_from_entitlement(ent)
            org_rows.append({
                "org": org,
                "upn": user["upn"],
                "access": access,
                "can_enable": access.lower() == "stakeholder",
                "entitlement_id": ent.get("id")
            })
        else:
            org_rows.append({
                "org": org,
                "upn": user["upn"],
                "access": "Not Found",
                "can_enable": False,
                "entitlement_id": None
            })
    return render_template("dashboard.html", user=user, org_rows=org_rows)

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/signin")
def signin():
    auth_url = msal_app.get_authorization_request_url(
        SCOPES,
        redirect_uri=url_for("authorized", _external=True, _scheme="https"),
        prompt="select_account"
    )
    return redirect(auth_url)

@app.route(REDIRECT_PATH)
def authorized():
    code = request.args.get("code")
    if not code:
        return "Missing authorization code", 400
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=url_for("authorized", _external=True, _scheme="https")
    )
    if "access_token" not in result:
        return f"Login failed: {result.get('error_description')}", 401

    access_token = result["access_token"]
    user_data = requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    session["graph_token"] = access_token  # for photo
    session["user"] = {
        "name": user_data.get("displayName"),
        "upn": user_data.get("userPrincipalName") or user_data.get("mail"),
    }
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(
        f"{AUTHORITY}/oauth2/v2.0/logout?post_logout_redirect_uri={url_for('index', _external=True, _scheme='https')}"
    )

@app.route("/me/photo")
def me_photo():
    token = session.get("graph_token")
    if not token:
        return redirect(url_for("login"))
    r = requests.get(
        "https://graph.microsoft.com/v1.0/me/photo/$value",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code == 200:
        return send_file(io.BytesIO(r.content), mimetype=r.headers.get("Content-Type", "image/jpeg"))
    # Fallback placeholder
    return send_file(io.BytesIO(b""), mimetype="image/jpeg")

@app.route("/enable_access", methods=["POST"])
def enable_access():
    if "user" not in session:
        return redirect(url_for("login"))
    if not AZURE_DEVOPS_PAT:
        flash("Server not configured with AZURE_DEVOPS_PAT", "error")
        return redirect(url_for("index"))

    org = request.form.get("org")
    upn = request.form.get("upn")
    entitlement_id = request.form.get("entitlement_id")

    if not org or not upn:
        flash("Missing parameters", "error")
        return redirect(url_for("index"))

    # If entitlement_id not supplied, look it up
    if not entitlement_id:
        ent, _ = _get_entitlements_for_org(org, upn)
        entitlement_id = ent.get("id") if ent else None

    if not entitlement_id:
        flash(f"User {upn} not found in org {org}", "error")
        return redirect(url_for("index"))

    ok, details = _set_basic_for_user(org, entitlement_id)
    if ok:
        flash(f"Access updated to Basic in {org}. Cost Associated $6/user/month", "success")
    else:
        flash(f"Failed to update access in {org}: {details}", "error")
    return redirect(url_for("index"))

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))  # Use Azure's port or default to 8000
    app.run(host="0.0.0.0", port=port)
# Gunicorn command for production
