"""
Core GenServer implementation.
"""

import logging
import queue
import threading
import uuid
from typing import (
    Any,
    Dict,
    Generic,
    Optional,
    Tuple,
    get_args,
    get_origin,
)

from genserver.exceptions import GenServerError, GenServerTimeoutError
from genserver.typing import CallMsg, CastMsg, StateType

# Configure default logger for the library
logger = logging.getLogger(__name__)
logger.addHandler(
    logging.NullHandler()
)  # To avoid 'No handler found' warnings if not configured by user

# ___________________ GenServer Messages ___________________


class Terminate:
    """
    A sentinel message used to signal that a TypedGenServer should stop running.

    When a Terminate message is placed in the server's mailbox, the server's
    message loop should exit gracefully, performing any necessary cleanup
    before shutting down.
    """

    pass


class Call(Generic[CallMsg]):
    """
    A synchronous request message sent to a TypedGenServer that expects a
    response.

    A Call wraps a request of type `CallMsg` along with a unique
    `correlation_id` that allows the sender to match the server's reply
    with the original request.

    Attributes
    ----------
    message : CallMsg
        The actual request payload.
    correlation_id : str
        A unique identifier that ties this call to its reply.
    """

    def __init__(self, message: CallMsg, correlation_id: str):
        self.message = message
        self.correlation_id = correlation_id


class Cast(Generic[CastMsg]):
    """
    An asynchronous request message sent to a GenServer.

    Unlike a `Call`, a `Cast` does not expect a reply. It simply delivers
    a message of type `CastMsg` to the server for handling.

    Attributes
    ----------
    message : CastMsg
        The request payload sent to the server.
    """

    def __init__(self, message: CastMsg):
        self.message = message


# _______________________ GenServers _______________________


class TypedGenServer(Generic[CastMsg, CallMsg, StateType]):
    """
    Typed Generic Server (GenServer) base class for Python.

    Has three generic parameters:

    1. `CastMsg`: The type of cast messages that it accepts.
    2. `CallMsg`: The type of call messages that it accepts.
    3. `StateType`: The type of its internal state.

    Implements the core GenServer behavior inspired by Erlang/OTP.
    Subclass this to create your own GenServers.

    Handles message queuing, state management, and basic lifecycle.
    """

    _cast_type: CastMsg
    _call_type: CallMsg
    _state_type: StateType

    def __init__(self) -> None:
        """
        Initializes the GenServer with a message queue and internal state.
        """
        self._mailbox: queue.Queue[Cast[CastMsg] | Call[CallMsg] | Terminate] = (
            queue.Queue()
        )
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._current_state: Optional[StateType] = None
        self._reply_queues: Dict[uuid.UUID, queue.Queue[Any]] = (
            {}
        )  # For handle_call replies

    def __init_subclass__(cls):
        super().__init_subclass__()

        # Julian: The original GenServer implementation checked that messages
        # were dictionaries. But, since we want to be able to check that messages
        # are any of the specified object, we need to get the type arguments of
        # the TypedGenServer when it gets subclassed. We can then store those
        # type arguments in the class variables and check the types of the
        # messages against them.
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is not TypedGenServer:
                continue
            cast_t, call_t, state_t = get_args(base)
            cls._cast_type = cast_t
            cls._call_type = call_t
            cls._state_type = state_t
            return

    # ------------- GenServer Lifecycle Management -------------

    def start(self, *args: Any, **kwargs: Any) -> None:
        """
        Starts the GenServer process.

        This method initializes the GenServer's state by calling `init(*args, **kwargs)`
        in a new thread and begins processing messages from the mailbox.

        Args:
            *args: Positional arguments to be passed to the `init` method.
            **kwargs: Keyword arguments to be passed to the `init` method.

        Raises:
            GenServerError: If the GenServer is already running.
        """
        if self._running:
            raise GenServerError("GenServer is already running.")
        self._running = True
        self._thread = threading.Thread(target=self._loop, args=args, kwargs=kwargs)
        self._thread.daemon = (
            False  # Non-daemon so threads aren't killed when main returns
        )
        self._thread.start()

    def stop(self, timeout: Optional[float] = None) -> None:
        """
        Stops the GenServer process gracefully.

        Sends a stop command to the GenServer's mailbox and waits for the thread to join.

        Args:
            timeout: Optional timeout in seconds to wait for the GenServer to stop.
                     If None, blocks indefinitely until stopped.

        Raises:
            GenServerError: If the GenServer is not running.
            TimeoutError: If the GenServer fails to stop within the timeout.
        """
        if not self._running:
            raise GenServerError("GenServer is not running.")
        self._running = False
        self._mailbox.put(Terminate())
        if self._thread is None:  # FIX 2: Check if _thread is not None
            return
        self._thread.join(timeout=timeout)
        # FIX 3: Check if _thread is not None before is_alive
        if self._thread.is_alive():
            raise TimeoutError("GenServer failed to stop within the timeout.")

    # ------------------ Message Type-checking -----------------

    def assert_cast_msg(self, message: CastMsg):
        """Asserts that the cast message is the correct type.

        Args:
            message (CastMsg): The message to be checked.

        Raises:
            GenServerError: If the message is not the correct type.
        """
        if not isinstance(message, self._cast_type):
            raise GenServerError(
                "Expected cast message %s, got %s",
                self._cast_type,
                type(message),
            )

    def assert_call_message(self, message):
        """Asserts that the call message is the correct type.

        Args:
            message (CastMsg): The message to be checked.

        Raises:
            GenServerError: If the message is not the correct type.
        """
        if not isinstance(message, self._call_type):
            raise GenServerError(
                "Expected call message %s, got %s",
                self._call_type,
                type(message),
            )

    # ------------------- Receiving Messages -------------------

    def cast(self, message: CastMsg) -> None:
        """
        Sends an asynchronous message (cast) to the TypedGenServer's mailbox.

        The TypedGenServer will process this message in its message processing loop.
        No response is expected for cast messages.

        Args:
            message: The message to be sent. Must be of type `CastMsg`.

        Raises:
            GenServerError: If the GenServer is not running or message is not the correct type.
        """
        if not self._running:
            raise GenServerError("Cannot cast message to a stopped GenServer.")
        # Enforce message as CastMsg type
        self.assert_cast_msg(message=message)
        cast_message = Cast(message=message)
        self._mailbox.put(cast_message)

    def call(self, message: CallMsg, timeout: Optional[float] = None) -> Any:
        """
        Sends a synchronous message (call) to the GenServer and waits for a response.

        This method blocks until the GenServer replies or a timeout occurs.

        Args:
            message: The message to be sent. Must be a dictionary.
            timeout: Optional timeout in seconds to wait for a response.
                     If None, blocks indefinitely.

        Returns:
            Any: The response from the GenServer.

        Raises:
            GenServerError: If the GenServer is not running or message is not a dictionary.
            GenServerTimeoutError: If no response is received within the timeout.
        """
        if not self._running:
            raise GenServerError("Cannot call a stopped GenServer.")
        # Enforce call message as CallMsg type
        self.assert_call_message(message=message)

        correlation_id = uuid.uuid4()
        reply_queue: queue.Queue[Any] = queue.Queue()
        self._reply_queues[correlation_id] = reply_queue
        call_message = Call(message=message, correlation_id=correlation_id)
        self._mailbox.put(call_message)

        try:
            response = reply_queue.get(
                timeout=timeout
            )  # Wait for response with timeout
            return response
        except queue.Empty:
            del self._reply_queues[correlation_id]  # Clean up
            raise GenServerTimeoutError(
                "No response received for call within timeout: %s seconds.", timeout
            )
        finally:
            if (
                correlation_id in self._reply_queues
            ):  # Ensure cleanup even if timeout didn't happen via queue.Empty
                del self._reply_queues[correlation_id]

    # ---------------------- Server State ----------------------

    @property
    def current_state(self):
        """Get or set the current state of the TypedGenServer.

        Returns:
            StateType: The current state of the TypedGenServer.

        Raises:
            GenServerError: If the set state is not the correct type.
        """
        return self._current_state

    @current_state.setter
    def current_state(self, value: StateType):
        if not isinstance(value, self._state_type):
            raise GenServerError(
                "Expected state %s, got %s",
                self._state_type,
                type(value),
            )
        self._current_state = value

    # ----------------- Responding to Messages -----------------

    def _reply(self, correlation_id: uuid.UUID, response: Any) -> None:
        """
        Internal method to send a reply to a 'call' message.

        Used by handle_call to send the response back to the caller.

        Args:
            correlation_id: The UUID of the call message to respond to.
            response: The response data.
        """
        reply_queue = self._reply_queues.get(correlation_id)
        if reply_queue:
            reply_queue.put(response)
        else:
            logger.warning(
                "Reply queue not found for correlation ID: %s. "
                "This might indicate a programming error or timeout.",
                correlation_id,
            )

    def _process_call(self, msg: Call):
        """Processes a `Call` message:

        1. Attempts to handle the message using the user-defined `handle_call`
           callback.
        2. Replies to the message-sender with a response.
        3. Sets the current state.
        4. In case of an exception, logs an exception and replies to the
           message-sender.

        Args:
            msg (Call): The message to process.
        """
        call_message = msg.message
        correlation_id = msg.correlation_id
        try:
            response, next_state = self.handle_call(call_message, self.current_state)
            self.current_state = next_state
            self._reply(
                correlation_id=correlation_id,
                response=response,
            )
        except Exception as e:
            logger.exception(
                "GenServer handle_call error for message: %s",
                call_message,
            )
            self._reply(
                correlation_id,
                GenServerError("handle_call failed: %s", e),
            )  # Reply with error

    def _process_cast(self, msg: Cast):
        """Processes a `Cast` message:

        1. Attempts to handle the message using the user-defined `handle_cast`
           callback.
        3. Sets the current state.
        4. In case of an exception, logs an exception.

        Args:
            msg (Cast): The message to process.
        """
        cast_message = msg.message
        try:
            next_state = self.handle_cast(cast_message, self.current_state)
            self.current_state = next_state
        except Exception as e:
            logger.exception(
                "GenServer handle_cast error for message: %s",
                cast_message,
            )

    def _loop(self, *args: Any, **kwargs: Any) -> None:
        """
        The main message processing loop of the GenServer.

        - Initializes state by calling `init`.
        - Continuously retrieves messages from the mailbox.
        - Handles different message types ('_command', '_call', cast messages).
        - Calls user-defined handler methods (`handle_cast`, `handle_call`).
        - Handles exceptions within handlers and logs them.
        - Calls `terminate` before exiting the loop.
        """
        try:
            self.current_state = self.init(*args, **kwargs)
        except Exception as e:
            logger.exception("GenServer init failed: %s", e)
            self._running = False  # Stop if init fails, prevent further processing
            return  # Exit loop immediately

        while self._running:
            try:
                msg = self._mailbox.get(
                    timeout=0.1
                )  # Block with timeout for responsiveness
                if not msg:  # Spurious wakeup?
                    continue
                if isinstance(msg, Terminate):
                    self._running = False
                    break
                elif isinstance(msg, Call):
                    self._process_call(msg)
                elif isinstance(msg, Cast):
                    self._process_cast(msg)
                else:
                    logger.warning("Unknown message type received: %s", msg)

            except queue.Empty:  # Timeout, just continue loop to check self._running
                pass  # No message in queue, non-blocking timeout used

            # Catch any unexpected errors in the loop
            except Exception as main_loop_err:
                logger.exception("GenServer main loop error: %s", main_loop_err)
                # Stop on unhandled loop errors to prevent indefinite issues
                self._running = False
                break  # Ensure loop exit

        try:
            self.terminate(self.current_state)  # Call terminate before thread exits
        except Exception as e_term:
            logger.exception("GenServer terminate error: %s", e_term)

    # -------- Callbacks to be Overridden in Subclasses --------

    def init(self, *args: Any, **kwargs: Any) -> StateType:
        """
        Initialization callback.

        Called when the GenServer starts. Should return the initial state.
        Override in subclass to define initial state and setup.

        Args:
            *args: Arguments passed from `start`.
            **kwargs: Keyword arguments passed from `start`.

        Returns:
            State: The initial state of the GenServer.
        """
        raise NotImplementedError("init method must be implemented in subclass.")

    def handle_cast(self, message: CastMsg, state: StateType) -> StateType:
        """
        Handles asynchronous cast messages.

        Override in subclass to define how to handle cast messages.

        Args:
            message: The cast message (dictionary).
            state: The current state of the GenServer.

        Returns:
            State: The new state of the GenServer after handling the message.
                   Return the same state if no state change is needed.
        """
        logger.warning(
            "Unhandled cast message: %s. Override handle_cast in subclass to handle it.",
            message,
        )
        return state  # Default: return same state

    def handle_call(self, message: CallMsg, state: StateType) -> Tuple[Any, StateType]:
        """
        Handles synchronous call messages.

        Override in subclass to define how to handle call messages.

        Args:
            message: The call message (dictionary).
            state: The current state of the GenServer.

        Returns:
            Tuple[Any, State]: A tuple containing:
                - The response to the call message.
                - The new state of the GenServer after handling the message.
                  Return the same state if no state change is needed.

        Raises:
            NotImplementedError: If not overridden in subclass.
        """
        raise NotImplementedError(
            "handle_call method must be implemented in subclass to handle calls."
        )

    def terminate(self, state: StateType) -> None:
        """
        Termination callback.

        Called when the GenServer is about to stop.
        Override in subclass to perform cleanup or final actions before shutdown.

        Args:
            state: The current state of the GenServer.
        """
        logger.info("GenServer is terminating.")
        pass  # Default: do nothing on terminate


class GenServer(
    TypedGenServer[dict, dict, StateType],
):
    """
    Generic Server (GenServer) base class for Python.

    Implements the core GenServer behavior inspired by Erlang/OTP.
    Subclass this to create your own GenServers.

    Specialises TypedGenServer to expect dictionaries for call and cast messages.

    Has one generic parameter:

    1. `StateType`: The type of its internal state.

    Handles message queuing, state management, and basic lifecycle.

    """

    pass

    def __init_subclass__(cls):
        # Julian: we have to duplicate the same "get type argument" logic as in
        # TypedGenServer to set the state type -- as when a GenServer gets
        # subclassed, the TypedGenServer __init_subclass__ will only see the
        # [dict, dict] type arguments, not the state type (as it's kept generic
        # in GenServer).

        super().__init_subclass__()
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is not GenServer:
                continue
            state_t = get_args(base)[0]
            cls._state_type = state_t
            return
