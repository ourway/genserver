import logging
import random
import time
import uuid

from genserver import GenServer, GenServerError

# Configure logging
logging.basicConfig(level=logging.INFO)


class InventoryManager(GenServer[dict]):
    """Manages inventory levels."""

    def init(self, initial_inventory):
        return initial_inventory

    def handle_cast(self, message, state):
        command = message.get("command")
        if command == "process_order":
            order = message.get("order")
            order_items = order.get("items", {})
            updated_inventory = state.copy()
            insufficient_items = []

            for item_name, quantity_needed in order_items.items():
                if item_name not in state or state[item_name] < quantity_needed:
                    insufficient_items.append(item_name)
                else:
                    updated_inventory[item_name] -= quantity_needed

            if insufficient_items:
                logging.warning(
                    f"Order {order.get('order_id')} - Insufficient stock for items: {insufficient_items}"
                )
                # For simplicity, OrderProcessor would need to handle this (e.g., retry, cancel)
                # In a real system, you might send a specific "inventory_unavailable" message back
            else:
                logging.info(f"Inventory updated for order {order.get('order_id')}")
                return updated_inventory  # Update inventory state

        elif command == "add_stock":
            item_name = message.get("item_name")
            quantity = message.get("quantity", 1)
            if item_name in state:
                state[item_name] += quantity
            else:
                state[item_name] = quantity
            logging.info(
                f"Added {quantity} of {item_name} to inventory. New stock: {state[item_name]}"
            )
        return state

    def handle_call(self, message, state):
        command = message.get("command")
        if command == "get_stock":
            item_name = message.get("item_name")
            stock_level = state.get(item_name, 0)
            return stock_level, state
        raise NotImplementedError(f"Call command '{command}' not implemented")


class OrderProcessor(GenServer[dict]):
    """Processes incoming orders."""

    def init(self, inventory_manager):
        self.inventory_manager = inventory_manager
        return {
            "processing_orders": {}
        }  # Track orders being processed (could be useful for status etc.)

    def handle_cast(self, message, state):
        command = message.get("command")
        if command == "process_order":
            order = message.get("order")
            order_id = order.get("order_id")
            if (
                order_id in state["processing_orders"]
            ):  # Simple retry mechanism to avoid duplicate processing
                logging.warning(
                    f"Order {order_id} already being processed. Ignoring duplicate request."
                )
                return state

            state["processing_orders"][order_id] = "processing"  # Mark as processing
            logging.info(f"Processing order {order_id}")
            time.sleep(random.uniform(0.2, 0.8))  # Simulate processing time

            fail_chance = 0.2  # 20% chance of processing failure
            if random.random() < fail_chance:
                logging.error(f"Order {order_id} processing failed!")
                del state["processing_orders"][order_id]  # Remove from processing
                # In a real system, you might want to implement retry queues, dead-letter queues, etc.
                # For this demo, we'll just log and drop the order after one failure.
            else:
                logging.info(
                    f"Order {order_id} processed successfully. Checking inventory."
                )
                del state["processing_orders"][order_id]  # Remove from processing
                self.inventory_manager.cast(
                    {"command": "process_order", "order": order}
                )  # Send to inventory manager

        return state

    def handle_call(self, message, state):
        command = message.get("command")
        if command == "get_order_status":
            order_id = message.get("order_id")
            status = state["processing_orders"].get(order_id, "unknown")
            return status, state
        raise NotImplementedError(f"Call command '{command}' not implemented")


class OrderDispatcher(GenServer[dict]):
    """Dispatches processed orders."""

    def init(self):
        return {"dispatched_orders": set()}

    def handle_cast(self, message, state):
        command = message.get("command")
        if command == "dispatch_order":
            order = message.get("order")
            order_id = order.get("order_id")
            logging.info(f"Dispatching order {order_id}")
            time.sleep(random.uniform(0.1, 0.5))  # Simulate dispatch time

            fail_chance = 0.1  # 10% chance of dispatch failure
            if random.random() < fail_chance:
                logging.error(f"Order {order_id} dispatch FAILED!")
                # Again, in a real system, you'd handle retries, alerts, etc.
            else:
                logging.info(f"Order {order_id} dispatched successfully.")
                state["dispatched_orders"].add(order_id)  # Track dispatched orders

        return state

    def handle_call(self, message, state):
        command = message.get("command")
        if command == "get_dispatched_count":
            return len(state["dispatched_orders"]), state
        raise NotImplementedError(f"Call command '{command}' not implemented")


class OrderGenerator(GenServer[int]):
    """Generates new orders periodically."""

    def init(self, order_processor):
        self.order_processor = order_processor
        return 0  # Order count

    def handle_cast(self, message, state):
        command = message.get("command")
        if command == "generate_order":
            state += 1
            order_id = str(uuid.uuid4())
            order = {
                "order_id": order_id,
                "items": {
                    "item_a": random.randint(1, 3),
                    "item_b": random.randint(0, 2),
                    "item_c": random.randint(1, 2),
                },
            }
            logging.info(f"Generated Order {order_id}: {order['items']}")
            self.order_processor.cast({"command": "process_order", "order": order})
            time.sleep(random.uniform(0.5, 1.5))  # Generate orders at intervals
            if self._running:  # <----- ADD THIS CHECK
                self.cast(
                    {"command": "generate_order"}
                )  # Continue generating only if still running
        return state

    def handle_call(self, message, state):
        command = message.get("command")
        if command == "get_order_count":
            return state, state
        raise NotImplementedError(f"Call command '{command}' not implemented")


if __name__ == "__main__":
    inventory = {"item_a": 20, "item_b": 15, "item_c": 25}
    inventory_manager = InventoryManager()
    inventory_manager.start(inventory)

    order_processor = OrderProcessor()
    order_processor.start(inventory_manager)

    order_dispatcher = OrderDispatcher()
    order_dispatcher.start()

    order_generator = OrderGenerator()
    order_generator.start(order_processor)

    # Add some stock to inventory after a bit to show dynamic updates
    time.sleep(5)
    inventory_manager.cast(
        {"command": "add_stock", "item_name": "item_b", "quantity": 10}
    )

    # Start generating orders
    order_generator.cast({"command": "generate_order"})

    print("Order processing system started. Let it run for a while...")
    time.sleep(20)  # Run for 20 seconds

    # Get some metrics before stopping
    dispatched_count = order_dispatcher.call(
        {"command": "get_dispatched_count"}, timeout=5
    )
    print(f"\n--- System Report ---")
    print(f"Total Dispatched Orders: {dispatched_count}")

    # Stop all GenServers gracefully
    print("\nStopping GenServers...")
    order_generator.stop()
    order_processor.stop()
    inventory_manager.stop()
    order_dispatcher.stop()

    print("Order processing system stopped.")
