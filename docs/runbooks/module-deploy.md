# Runbook: deploying and retiring module code

Enabling or disabling a module **for a tenant** is instant (a catalog toggle). Adding or
removing a module's **code** is a deploy, because `INSTALLED_APPS` is fixed at process
startup (limit **D9**): a new package is not importable until the process restarts.

## Add a new module

1. **Scaffold** (local): `python manage.py startmodule <id> [--requires <dep>] [--optional <dep>]`.
   This writes `easybiz/modules/<id>/` (a worked-sample, contract-clean module) and appends the
   package to `EASYBIZ_MODULES` in `.env`. Build it out, then prove it:
   `python manage.py check_module <id>` (and `pytest -m module_contract`).
2. **Build an image** that contains the new package and has `EASYBIZ_MODULES` listing it.
3. **Deploy / rolling restart** so every process imports the new package.
4. **Record it in the catalog**: `python manage.py upgrade_modules` (runs `sync_modules` +
   applies any shared/enabled-tenant migrations). The module is now installed but enabled for
   no one.
5. **Enable per tenant** as needed: `python manage.py tenant_module <slug> enable <id>` (or the
   `/api/core/modules/<id>/enable` endpoint). This migrates the module's tables into that
   tenant's schema and seeds its roles.

Roll back by deploying the previous image; disable per tenant first if the new version is bad.

## Retire a module

1. **Disable + remove data per tenant**: `tenant_module <slug> disable <id>`, then
   `/api/core/modules/<id>/data?confirm=true` (drops the module's tables in that schema).
   Repeat until no tenant has a row.
2. **Uninstall from the catalog**: `python manage.py uninstall_module <id>` — refused while any
   tenant still holds a `TenantModule` row; it removes the catalog `Module` and `Permission`
   rows.
3. **Remove the code** in a subsequent deploy (drop the package from `EASYBIZ_MODULES` and the
   image). Code removal is always a deploy step (D9).
