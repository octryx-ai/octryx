---
title: Providers
---

Every model call goes through LiteLLM. Models of the bundled LiteLLM are managed in the **Models (bundled LiteLLM)** table; an external LiteLLM gateway is added here as a provider. Which models are offered, approved and used is set in the Model catalog.

### What you do here
- Add a model to the bundled LiteLLM and test it.
- Add an external LiteLLM gateway with **Add provider**.
- Assign providers to Workspaces.

### Next steps
- [Review the model catalog](/chat?area=admin&tab=modelCatalog)
- [Set the default model](/chat?area=admin&tab=modelOrder)

### The LiteLLM gateway panel
- **State** is the gateway's last check in words; hover it for the check's code.
- **Gateway key**: the key is never shown here, only whether it is linked. A platform operator links it on the server; until then the gateway needs configuration.
- **Address**: the gateway origin, or the `/v1` prefix. Only https, except on the local machine; no user name, query or fragment.
- **Allowed hosts**: bare host names, separated by commas or new lines; no scheme, port, path or wildcard. The address's host must be listed, or the gateway stays not ready.
- **Timeout in seconds**: optional, 5 to 600; empty uses the server default.
- **Models**: each entry maps a model name people and agents ask for onto a gateway model. A new entry sets once up to which data class it is cleared, its capabilities, which sensitive data it is approved for and its price; after that these are changed in Models › Catalog, and each Workspace chooses which models it may use.
- **Approved for sensitive data**: only a model approved for a category can be the route target of a content policy for it (`resource.approved_for` in policies). Changes are audited; a policy that routes to the model shows a warning when its category is removed.
- **Price**: *Priced here* needs input and output prices above zero; *Priced by the gateway* needs the gateway to report a cost; *Free, under a governance record* names the record.
- **Technical details**: how the gateway lists its models (path, response format and the field that names a model). They are fixed by configuration, never guessed; a value outside the supported ones keeps the gateway not ready.
- **Save changes** sends the settings to the server, which checks them again; **Reset** returns to the stored settings.
