import json, msal
from graph_client import acquire_token  # uses your loader

def main():
    with open("graph_config.json","rb") as f:
        cfg = json.load(f)
    try:
        token = acquire_token(cfg)  # if you patched this earlier, it prints details
        print(token)
    except Exception as e:
        # If acquire_token raises without printing MSAL result, try direct MSAL to show full error:
        tenant = cfg["tenant_id"]
        client = cfg["client_id"]
        authority = cfg.get("authority") or f"https://login.microsoftonline.com/{tenant}"
        scope = cfg.get("scope") or "https://graph.microsoft.com/.default"

        # Reuse the same key/cert that acquire_token() would produce
        from graph_client import _load_from_pfx_b64, _load_from_pfx_path
        if "pfx_base64" in cfg:
            key, cert, thumb = _load_from_pfx_b64(cfg["pfx_base64"], cfg.get("pfx_password_env"))
        else:
            key, cert, thumb = _load_from_pfx_path(cfg["pfx_path"], cfg.get("pfx_password_env"))

        app = msal.ConfidentialClientApplication(
            client_id=client,
            authority=authority,
            client_credential={"private_key": key, "thumbprint": thumb, "cert": cert},
        )
        res = app.acquire_token_for_client(scopes=[scope])
        print("MSAL result:", json.dumps(res, indent=2))
        raise

if __name__ == "__main__":
    main()
