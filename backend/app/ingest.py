import asyncio
import json
import signal
from typing import Any, Dict, Optional

from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
    ConfigurationWebSocketStreams,
)

from .config import KAFKA_BROKER, RAW_TOPIC, RAW_TOPIC_PARTITIONS, PROCESSED_TOPIC, PROCESSED_TOPIC_PARTITIONS


def _ensure_topics() -> None:
    admin = KafkaAdminClient(bootstrap_servers=KAFKA_BROKER)
    existing = {topic for topic in admin.list_topics()}
    topics = []
    if RAW_TOPIC not in existing:
        topics.append(NewTopic(name=RAW_TOPIC, num_partitions=RAW_TOPIC_PARTITIONS, replication_factor=1))
    if PROCESSED_TOPIC not in existing:
        topics.append(NewTopic(name=PROCESSED_TOPIC, num_partitions=PROCESSED_TOPIC_PARTITIONS, replication_factor=1))
    if topics:
        admin.create_topics(topics)
    admin.close()


async def main() -> None:
    _ensure_topics()
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        key_serializer=lambda k: k.encode("utf-8"),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    stop_event = asyncio.Event()

    def _to_dict(value: Any) -> Any:
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if hasattr(value, "model_dump"):
            return value.model_dump(by_alias=True)
        return value

    def handle_message(msg: Any) -> None:
        payload = _to_dict(msg)
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            for item in data:
                ev = _to_dict(item)
                if isinstance(ev, dict):
                    sym = ev.get("s")
                    if sym:
                        producer.send(RAW_TOPIC, key=sym, value=ev)
        else:
            ev = _to_dict(data)
            if isinstance(ev, dict):
                sym = ev.get("s")
                if sym:
                    producer.send(RAW_TOPIC, key=sym, value=ev)

    def shutdown(*_: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    configuration_ws_streams = ConfigurationWebSocketStreams(
        stream_url=DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
    )
    client = DerivativesTradingUsdsFutures(config_ws_streams=configuration_ws_streams)

    connection: Optional[Any] = None
    stream = None
    try:
        connection = await client.websocket_streams.create_connection()
        stream = await connection.all_market_tickers_streams()
        stream.on("message", handle_message)

        await stop_event.wait()
    finally:
        if stream is not None:
            await stream.unsubscribe()
        if connection is not None:
            await connection.close_connection(close_session=True)
        producer.flush(5)
        producer.close()


if __name__ == "__main__":
    asyncio.run(main())
