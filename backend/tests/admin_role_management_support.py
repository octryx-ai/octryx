"""The login helper shared by the test_admin_role_* modules."""


async def _auth_headers_for(client, username: str, password: str = "password123") -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
