import { useState } from "react";

export function useAdminCreateUserState() {
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newAccountType, setNewAccountType] = useState("human");
  const [newRoles, setNewRoles] = useState("viewer");
  const [formError, setFormError] = useState<string | null>(null);
  const [formLoading, setFormLoading] = useState(false);

  return {
    formError,
    setFormError,
    formLoading,
    setFormLoading,
    newDisplayName,
    setNewDisplayName,
    newAccountType,
    setNewAccountType,
    newEmail,
    setNewEmail,
    newPassword,
    setNewPassword,
    newRoles,
    setNewRoles,
    newUsername,
    setNewUsername,
    showCreateUser,
    setShowCreateUser,
  };
}
