# Accounts API — Reference

Base path: `/api/v1/accounts/`  
Authentication: `Authorization: Bearer <access_token>`

---

## Authentication Flow

```
POST /api/v1/auth/login/
Body: { "username": "hamisi", "password": "..." }
Response: { "access": "eyJ...", "refresh": "eyJ..." }

# Use access token in all subsequent requests:
Authorization: Bearer eyJ...

# When access expires (60 min), refresh:
POST /api/v1/auth/refresh/
Body: { "refresh": "eyJ..." }
Response: { "access": "eyJ..." }
```

---

## Endpoints

### Current User

| Method | Path | Description |
|--------|------|-------------|
| GET | `/me/` | Get logged-in user profile |
| PATCH | `/me/` | Update profile (name, phone, etc.) |
| POST | `/me/change-password/` | Change password |

### Users (Admin only)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/users/` | List all users (`?role=cashier`, `?store=<id>`) |
| POST | `/users/` | Create new user |
| GET | `/users/{id}/` | Get user by ID |
| PATCH | `/users/{id}/` | Update user |
| DELETE | `/users/{id}/` | Deactivate user |

### Stores

| Method | Path | Description |
|--------|------|-------------|
| GET | `/stores/` | List stores (admin: all; others: own store) |
| POST | `/stores/` | Create store (admin only) |
| GET | `/stores/{id}/` | Store detail |
| PATCH | `/stores/{id}/` | Update store |

### Organisation

| Method | Path | Description |
|--------|------|-------------|
| GET | `/organisation/` | Get organisation settings |
| PATCH | `/organisation/` | Update org settings |

### AI Credits

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ai-credits/` | Current month AI credit usage |

---

## Standard Response

All endpoints return:
```json
{
  "success": true,
  "message": "User profile retrieved.",
  "data": { ... },
  "errors": null
}
```

## Roles

| Role | Can Do |
|------|--------|
| `admin` | Everything |
| `manager` | Store management, view reports |
| `cashier` | POS only, view own transactions |
