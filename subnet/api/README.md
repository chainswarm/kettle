# RocksDB API

A production-ready REST API for querying RocksDB database with versioned endpoints, automatic documentation, and Docker support.

## Features

- ✅ **Read-only access** - Safe concurrent access with peer process
- ✅ **Versioned API** - `/api/v1.0/...` endpoints
- ✅ **Auto documentation** - Swagger UI and ReDoc
- ✅ **Type-safe** - Pydantic models for validation
- ✅ **Docker ready** - Containerized deployment
- ✅ **Health checks** - Monitoring and metrics
- ✅ **Pagination** - Efficient handling of large datasets

## Architecture

```
┌─────────────────────┐
│   Peer Process      │  ← Writes to RocksDB
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   RocksDB (disk)    │  ← Shared database
└──────────▲──────────┘
           │
┌──────────┴──────────┐
│   FastAPI Service   │  ← Read-only access
│   (subnet/api/)     │
└─────────────────────┘
```

## Installation

### Install Dependencies

```bash
# Install the package with API dependencies
pip install -e .
```

The following dependencies will be installed:
- `fastapi>=0.115.0` - Web framework
- `uvicorn[standard]>=0.32.0` - ASGI server
- `pydantic>=2.0.0` - Data validation
- `pydantic-settings>=2.0.0` - Settings management

## Quick Start

### 1. Set Database Path

```bash
export API_DB_PATH=/path/to/your/rocksdb
```

### 2. Run the API Server

```bash
run_api
```

The API will be available at:
- **API**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/api/docs
- **ReDoc**: http://localhost:8000/api/redoc

### 3. Test the API

```bash
# Health check
curl http://localhost:8000/api/v1.0/health

# List all peers
curl http://localhost:8000/api/v1.0/peers

# Get specific peer
curl http://localhost:8000/api/v1.0/peers/QmPeerID123
```

## Configuration

All settings can be configured via environment variables with the `API_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `API_DB_PATH` | `/tmp/rocksdb` | Path to RocksDB database |
| `API_HOST` | `0.0.0.0` | API server host |
| `API_PORT` | `8000` | API server port |
| `API_DB_READ_ONLY` | `true` | Open database in read-only mode |
| `API_RELOAD` | `false` | Enable auto-reload (development) |
| `API_DEFAULT_PAGE_SIZE` | `100` | Default pagination size |
| `API_MAX_PAGE_SIZE` | `1000` | Maximum pagination size |

### Example: Custom Configuration

```bash
API_DB_PATH=/data/rocksdb \
API_PORT=9000 \
API_RELOAD=true \
run_api
```

## API Endpoints

### Health & Metrics

- `GET /api/v1.0/health` - Health check
- `GET /api/v1.0/health/metrics` - API metrics

### Peers

- `GET /api/v1.0/peers` - List all peers (with pagination)
- `GET /api/v1.0/peers/{peer_id}` - Get specific peer

### Named Maps (nmaps)

- `GET /api/v1.0/nmaps` - List all named maps
- `GET /api/v1.0/nmaps/{nmap_name}` - Get all entries in a named map
- `GET /api/v1.0/nmaps/{nmap_name}/{key}` - Get specific entry (supports composite keys)

### Keys

- `GET /api/v1.0/keys` - List all keys (with pagination)
- `GET /api/v1.0/keys/{key}` - Get value by key
- `GET /api/v1.0/keys/nested/{k1}` - Get all nested keys under k1
- `GET /api/v1.0/keys/nested/{k1}/{k2}` - Get specific nested key

## Docker Deployment

### Build the Image

```bash
docker build -t rocksdb-api .
```

### Run with Docker

```bash
docker run -d \
  -p 8000:8000 \
  -v /path/to/rocksdb:/data/rocksdb:ro \
  -e API_DB_PATH=/data/rocksdb \
  rocksdb-api
```

### Run with Docker Compose

1. Edit `docker-compose.yml` and update the volume path:

```yaml
volumes:
  - /path/to/your/rocksdb:/data/rocksdb:ro
```

2. Start the service:

```bash
docker-compose up -d
```

3. View logs:

```bash
docker-compose logs -f api
```

4. Stop the service:

```bash
docker-compose down
```

## Development

### Run in Development Mode

```bash
API_RELOAD=true run_api
```

This enables auto-reload when code changes.

### Access API Documentation

Visit http://localhost:8000/api/docs for interactive Swagger UI where you can:
- Browse all endpoints
- Test API calls directly
- View request/response schemas
- Download OpenAPI specification

## Example Usage

### Python Client

```python
import requests

# Base URL
base_url = "http://localhost:8000/api/v1.0"

# Health check
response = requests.get(f"{base_url}/health")
print(response.json())

# List peers with pagination
response = requests.get(f"{base_url}/peers", params={"limit": 10, "offset": 0})
peers = response.json()
print(f"Total peers: {peers['total']}")

# Get specific peer
peer_id = "QmPeerID123"
response = requests.get(f"{base_url}/peers/{peer_id}")
peer_data = response.json()

# Get all entries in a named map
response = requests.get(f"{base_url}/nmaps/heartbeats")
heartbeats = response.json()

# Get specific entry with composite key
response = requests.get(f"{base_url}/nmaps/heartbeats/subnet_1:node_5")
entry = response.json()
```

### JavaScript/TypeScript Client

```javascript
const baseUrl = "http://localhost:8000/api/v1.0";

// Health check
const health = await fetch(`${baseUrl}/health`).then(r => r.json());

// List peers
const peers = await fetch(`${baseUrl}/peers?limit=10&offset=0`)
  .then(r => r.json());

// Get specific peer
const peer = await fetch(`${baseUrl}/peers/QmPeerID123`)
  .then(r => r.json());
```

### cURL Examples

```bash
# Health check
curl http://localhost:8000/api/v1.0/health

# Metrics
curl http://localhost:8000/api/v1.0/health/metrics

# List peers with pagination
curl "http://localhost:8000/api/v1.0/peers?limit=10&offset=0"

# Get specific peer
curl http://localhost:8000/api/v1.0/peers/QmPeerID123

# List all named maps
curl http://localhost:8000/api/v1.0/nmaps

# Get all entries in a named map
curl http://localhost:8000/api/v1.0/nmaps/heartbeats

# Get specific entry (composite key)
curl http://localhost:8000/api/v1.0/nmaps/heartbeats/subnet_1:node_5

# List keys with pagination
curl "http://localhost:8000/api/v1.0/keys?limit=100&offset=0"

# Get nested keys
curl http://localhost:8000/api/v1.0/keys/nested/subnet_1?recursive=true
```

## Production Considerations

### Security

- **Read-only mode**: API opens database in read-only mode by default
- **CORS**: Configure `API_CORS_ORIGINS` for production
- **Rate limiting**: Consider adding rate limiting middleware
- **Authentication**: Add API key authentication for production

### Performance

- **Pagination**: Use `limit` and `offset` parameters for large datasets
- **Caching**: Consider adding Redis for frequently accessed data
- **Monitoring**: Use Prometheus + Grafana (see docker-compose.yml)

### Monitoring

The API includes built-in health checks and metrics:

```bash
# Health check
curl http://localhost:8000/api/v1.0/health

# Metrics (key count, DB size, uptime)
curl http://localhost:8000/api/v1.0/health/metrics
```

## Troubleshooting

### Database Not Found

```
FileNotFoundError: Database not found at /path/to/db_store
```

**Solution**: Ensure `API_DB_PATH` points to the correct RocksDB directory (without the `_store` suffix).

### Port Already in Use

```
OSError: [Errno 98] Address already in use
```

**Solution**: Change the port using `API_PORT=9000 run_api` or stop the process using port 8000.

### Permission Denied

```
PermissionError: [Errno 13] Permission denied
```

**Solution**: Ensure the API process has read permissions for the RocksDB directory.

## License

Same as the parent project (MIT AND Apache-2.0).
