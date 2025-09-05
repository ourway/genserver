from functools import singledispatchmethod
import logging
import time
import unittest

from genserver.core import TypedGenServer, GenServerError, GenServerTimeoutError

# Configure logging for tests (optional, but helpful for debugging)
logging.basicConfig(level=logging.INFO)


class Increment:
    pass


class Decrement:
    pass


class GetCount:
    pass


class IncrementAndGet:
    pass


class CounterServer(
    TypedGenServer[Increment | Decrement, GetCount | IncrementAndGet, int]
):  # Example with state as int
    def init(self) -> int:
        return 0  # Initial state is 0

    @singledispatchmethod
    def handle_cast(self, message, state: int) -> int:
        return super().handle_cast(message, state)

    @handle_cast.register
    def _(self, message: Increment, state: int) -> int:
        return state + 1

    @handle_cast.register
    def _(self, message: Decrement, state: int) -> int:
        return state - 1

    @singledispatchmethod
    def handle_call(self, message, state: int) -> tuple[int, int]:
        raise NotImplementedError("Call message %s not implemented.", message)

    @handle_call.register
    def _(self, message: GetCount, state: int) -> tuple[int, int]:
        return state, state

    @handle_call.register
    def _(self, message: IncrementAndGet, state: int) -> tuple[int, int]:
        new_state = state + 1
        return new_state, new_state


class ErrorCall:
    pass


class ErrorCast:
    pass


class TestGenServer(unittest.TestCase):

    def test_start_stop(self):
        server = CounterServer()
        server.start()
        self.assertTrue(server._running)
        server.stop()
        self.assertFalse(server._running)

    def test_double_start_stop(self):
        server = CounterServer()
        server.start()
        with self.assertRaises(GenServerError):
            server.start()  # Should raise error if already running
        server.stop()
        with self.assertRaises(GenServerError):
            server.stop()  # Should raise error if already stopped

    def test_cast_increment(self):
        server = CounterServer()
        server.start()
        server.cast(Increment())
        time.sleep(0.1)  # Allow time for message processing
        count = server.call(GetCount())
        self.assertEqual(count, 1)
        server.stop()

    def test_cast_decrement(self):
        server = CounterServer()
        server.start()
        server.cast(Decrement())
        time.sleep(0.1)
        count = server.call(GetCount())
        self.assertEqual(count, -1)
        server.stop()

    def test_call_get_count(self):
        server = CounterServer()
        server.start()
        count = server.call(GetCount())
        self.assertEqual(count, 0)
        server.stop()

    def test_call_increment_and_get(self):
        server = CounterServer()
        server.start()
        new_count = server.call(IncrementAndGet())
        self.assertEqual(new_count, 1)
        count = server.call(GetCount())  # Verify state is updated
        self.assertEqual(count, 1)
        server.stop()

    def test_call_timeout(self):
        class TimeoutServer(TypedGenServer[None, object, None]):
            def init(self):
                return None

            def handle_call(self, message, state):
                time.sleep(1)  # Simulate long processing
                return "response", state

        server = TimeoutServer()
        server.start()
        start_time = time.time()
        with self.assertRaises(GenServerTimeoutError):
            server.call({"action": "test"}, timeout=0.1)  # Short timeout
        elapsed_time = time.time() - start_time
        self.assertLess(
            elapsed_time, 0.5
        )  # Should be much less than 1 sec sleep in handler
        server.stop()

    def test_terminate_callback(self):
        class TerminateTestServer(TypedGenServer[None, None, list]):
            def init(self):
                return []

            def terminate(self, state):
                state.append("terminated")  # Modify state on terminate

        server = TerminateTestServer()
        server.start()
        server.stop()
        self.assertEqual(
            server._current_state, ["terminated"]
        )  # Check state after stop

    def test_init_exception_handling(self):
        class InitErrorServer(TypedGenServer[object, object, None]):
            def init(self):
                raise ValueError("Init failed")  # Simulate init failure

            def handle_cast(self, message, state):
                return state

            def handle_call(self, message, state):
                return "response", state

        server = InitErrorServer()
        server.start()  # Start should not raise, but GenServer should stop internally
        time.sleep(0.1)  # Give time for thread to run and stop
        self.assertFalse(server._running)  # Should not be running after init failure
        with self.assertRaises(GenServerError):  # Check cast and call fail
            server.cast({"action": "test"})
        with self.assertRaises(GenServerError):
            server.call({"action": "test"})

    def test_handler_exception_handling(self):
        class HandlerErrorServer(TypedGenServer[object, object, None]):
            def init(self):
                return None

            @singledispatchmethod
            def handle_cast(self, message, state):
                return state

            @handle_cast.register
            def _(self, message: ErrorCast, state):
                raise TypeError("Cast handler error")

            @singledispatchmethod
            def handle_call(self, message, state):
                return "response", state

            @handle_call.register
            def _(self, message: ErrorCall, state):
                raise ValueError("Call handler error")

        server = HandlerErrorServer()
        server.start()

        # Cast error should be logged, but GenServer should continue running
        server.cast(ErrorCast())
        time.sleep(0.1)  # Allow time for error to be logged and handled
        self.assertTrue(server._running)  # Still running after cast error

        # Call error should also be handled, and exception returned to caller via call
        response = server.call(ErrorCall())  # Capture the returned response
        self.assertIsInstance(
            response, GenServerError
        )  # Assert response is GenServerError
        with self.assertRaises(
            GenServerError
        ):  # Now assert that *raising* this response raises GenServerError
            raise response

        server.stop()


if __name__ == "__main__":
    unittest.main()
