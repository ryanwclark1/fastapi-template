"""Cache management commands."""

import sys

import click

from example_service.cli.utils import coro, error, info, success, warning
from example_service.core.settings import get_redis_settings


@click.group(name="cache")
def cache() -> None:
    """Cache management commands."""


@cache.command()
@coro
async def test() -> None:
    """Test Redis cache connectivity."""
    info("Testing Redis connection...")

    try:
        redis_settings = get_redis_settings()

        info(f"Connecting to: {redis_settings.redis_url}")

        redis = get_cache()

        # Test ping
        response = await redis.ping()
        if response:
            success("Redis connection successful!")
        else:
            error("Redis ping failed")
            sys.exit(1)

        # Get server info
        info_dict = await redis.info("server")
        info(f"Redis version: {info_dict.get('redis_version', 'unknown')}")
        info(f"Redis mode: {info_dict.get('redis_mode', 'unknown')}")

        await redis.aclose()

    except Exception as e:
        error(f"Failed to connect to Redis: {e}")
        sys.exit(1)


@cache.command()
@coro
async def info_cmd() -> None:
    """Display Redis server information and statistics."""
    info("Fetching Redis server information...")

    try:
        redis = get_cache()

        # Get server info
        server_info = await redis.info("server")
        click.echo("\n📊 Server Information:")
        click.echo(f"  Redis version: {server_info.get('redis_version')}")
        click.echo(f"  OS: {server_info.get('os')}")
        click.echo(f"  Architecture: {server_info.get('arch_bits')} bits")
        click.echo(f"  Uptime: {server_info.get('uptime_in_days')} days")

        # Get memory info
        memory_info = await redis.info("memory")
        used_memory = int(memory_info.get("used_memory", 0))
        used_memory_human = memory_info.get("used_memory_human")
        click.echo("\n💾 Memory Usage:")
        click.echo(f"  Used memory: {used_memory_human}")
        click.echo(f"  Peak memory: {memory_info.get('used_memory_peak_human')}")
        click.echo(f"  Memory fragmentation: {memory_info.get('mem_fragmentation_ratio')}")

        # Get stats
        stats_info = await redis.info("stats")
        click.echo("\n📈 Statistics:")
        click.echo(f"  Total connections: {stats_info.get('total_connections_received')}")
        click.echo(f"  Total commands: {stats_info.get('total_commands_processed')}")
        click.echo(f"  Keyspace hits: {stats_info.get('keyspace_hits')}")
        click.echo(f"  Keyspace misses: {stats_info.get('keyspace_misses')}")

        # Get key count
        db_info = await redis.info("keyspace")
        if db_info:
            click.echo("\n🔑 Keyspace:")
            for db_name, db_data in db_info.items():
                click.echo(f"  {db_name}: {db_data}")
        else:
            click.echo("\n🔑 Keyspace: Empty")

        await redis.aclose()
        success("\nRedis info retrieved successfully!")

    except Exception as e:
        error(f"Failed to get Redis info: {e}")
        sys.exit(1)


@cache.command()
@click.option(
    "--pattern",
    default="*",
    help="Key pattern to flush (default: all keys)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Skip confirmation prompt",
)
@coro
async def flush(pattern: str, force: bool) -> None:
    """Flush Redis cache keys matching pattern."""
    if pattern == "*":
        warning("⚠ This will DELETE ALL KEYS from Redis cache!")
    else:
        warning(f"⚠ This will delete all keys matching pattern: {pattern}")

    if not force and not click.confirm("Are you sure you want to continue?"):
        info("Flush cancelled")
        return

    info("Flushing cache...")

    try:
        redis = get_cache()

        if pattern == "*":
            # Flush all keys
            await redis.flushdb()
            success("All cache keys flushed successfully!")
        else:
            # Delete keys matching pattern
            cursor = 0
            deleted_count = 0

            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted = await redis.delete(*keys)
                    deleted_count += deleted

                if cursor == 0:
                    break

            success(f"Deleted {deleted_count} keys matching pattern '{pattern}'")

        await redis.aclose()

    except Exception as e:
        error(f"Failed to flush cache: {e}")
        sys.exit(1)


@cache.command()
@click.option(
    "--pattern",
    default="*",
    help="Key pattern to search for (default: all keys)",
)
@click.option(
    "--limit",
    default=100,
    type=int,
    help="Maximum number of keys to display",
)
@coro
async def keys(pattern: str, limit: int) -> None:
    """List cache keys matching pattern."""
    info(f"Searching for keys matching pattern: {pattern}")

    try:
        redis = get_cache()

        all_keys = []
        cursor = 0

        while len(all_keys) < limit:
            cursor, found_keys = await redis.scan(cursor, match=pattern, count=100)
            all_keys.extend([key.decode() if isinstance(key, bytes) else key for key in found_keys])

            if cursor == 0:
                break

        # Limit results
        all_keys = all_keys[:limit]

        if all_keys:
            click.echo(f"\n🔑 Found {len(all_keys)} keys:")
            for key in all_keys:
                # Get key type and TTL
                key_type = await redis.type(key)
                ttl = await redis.ttl(key)

                ttl_str = f"{ttl}s" if ttl > 0 else "∞" if ttl == -1 else "expired"
                click.echo(f"  • {key} (type: {key_type}, ttl: {ttl_str})")

            if len(all_keys) == limit:
                info(f"\n(Limited to {limit} keys. Use --limit to see more)")
        else:
            warning("No keys found matching pattern")

        await redis.aclose()

    except Exception as e:
        error(f"Failed to list cache keys: {e}")
        sys.exit(1)


@cache.command()
@click.argument("key")
@coro
async def get(key: str) -> None:
    """Get value of a cache key."""
    info(f"Retrieving value for key: {key}")

    try:
        redis = get_cache()

        # Check if key exists
        exists = await redis.exists(key)
        if not exists:
            warning(f"Key '{key}' does not exist")
            await redis.aclose()
            return

        # Get key type
        key_type = await redis.type(key)

        # Get value based on type
        if key_type == "string":
            value = await redis.get(key)
            click.echo(f"\n🔑 {key} (string):")
            click.echo(f"  {value}")
        elif key_type == "list":
            values = await redis.lrange(key, 0, -1)
            click.echo(f"\n🔑 {key} (list, {len(values)} items):")
            for idx, val in enumerate(values):
                click.echo(f"  [{idx}] {val}")
        elif key_type == "set":
            values = await redis.smembers(key)
            click.echo(f"\n🔑 {key} (set, {len(values)} items):")
            for val in values:
                click.echo(f"  • {val}")
        elif key_type == "hash":
            values = await redis.hgetall(key)
            click.echo(f"\n🔑 {key} (hash, {len(values)} fields):")
            for field, val in values.items():
                click.echo(f"  {field}: {val}")
        else:
            info(f"Key type '{key_type}' not fully supported for display")

        # Get TTL
        ttl = await redis.ttl(key)
        ttl_str = f"{ttl}s" if ttl > 0 else "no expiration" if ttl == -1 else "expired"
        info(f"TTL: {ttl_str}")

        await redis.aclose()

    except Exception as e:
        error(f"Failed to get cache key: {e}")
        sys.exit(1)
