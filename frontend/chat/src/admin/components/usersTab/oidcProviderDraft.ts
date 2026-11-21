// The draft of a new OIDC provider in the Register OIDC provider form.
export type NewOidcProvider = {
  name: string;
  issuerUrl: string;
  discoveryUrl: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
};

export const EMPTY_OIDC_PROVIDER: NewOidcProvider = {
  name: "",
  issuerUrl: "",
  discoveryUrl: "",
  clientId: "",
  clientSecret: "",
  scopes: "openid, profile, email",
};
