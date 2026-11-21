type NamedUser = { username: string; display_name?: string | null };

/** How a person is named in confirmations and notices: the display name, else the username. */
export function userDisplayName(user: NamedUser): string {
  return user.display_name?.trim() || user.username;
}
