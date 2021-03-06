#-----------------------------------------------------------------------------
# Copyright (c) 2012 - 2020, Anaconda, Inc., and Bokeh Contributors.
# All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
#-----------------------------------------------------------------------------
''' Utilities for generating and manipulating session IDs.

A session ID would typically be associated with each browser tab viewing
an application or plot. Each session has its own state separate from any
other sessions hosted by the server.

'''

#-----------------------------------------------------------------------------
# Boilerplate
#-----------------------------------------------------------------------------
import logging # isort:skip
log = logging.getLogger(__name__)

#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------

# Standard library imports
import base64
import codecs
import hashlib
import hmac
import time
from typing import Any, Optional, Tuple, Union

# Bokeh imports
from bokeh.settings import settings

#-----------------------------------------------------------------------------
# Globals and constants
#-----------------------------------------------------------------------------

__all__ = (
    'check_session_id_signature',
    'generate_secret_key',
    'generate_session_id',
)

#-----------------------------------------------------------------------------
# General API
#-----------------------------------------------------------------------------

def generate_secret_key() -> str:
    """
    Generate a new securely-generated secret key appropriate
    for SHA-256 HMAC signatures. This key could be used to
    sign Bokeh server session IDs for example.
    """
    return _get_random_string()

def generate_session_id(secret_key: Optional[bytes] = settings.secret_key_bytes(),
                        signed: bool = settings.sign_sessions()) -> str:
    """Generate a random session ID.
    Typically, each browser tab connected to a Bokeh application
    has its own session ID.  In production deployments of a Bokeh
    app, session IDs should be random and unguessable - otherwise
    users of the app could interfere with one another.

    If session IDs are signed with a secret key, the server can
    verify that the generator of the session ID was "authorized"
    (the generator had to know the secret key). This can be used
    to have a separate process, such as another web application,
    which generates new sessions on a Bokeh server. This other
    process may require users to log in before redirecting them to
    the Bokeh server with a valid session ID, for example.

    Args:
        secret_key (str, optional) : Secret key (default: value of 'BOKEH_SECRET_KEY' env var)
        signed (bool, optional) : Whether to sign the session ID (default: value of
                                  'BOKEH_SIGN_SESSIONS' env var)

    """
    secret_key = _ensure_bytes(secret_key)
    if signed:
        # note: '-' can also be in the base64 encoded signature
        base_id = _get_random_string(secret_key=secret_key)
        return base_id + '-' + _signature(base_id, secret_key)
    else:
        return _get_random_string(secret_key=secret_key)

def check_session_id_signature(session_id: str,
                               secret_key: Optional[bytes] = settings.secret_key_bytes(),
                               signed: Optional[bool] = settings.sign_sessions()) -> bool:
    """Check the signature of a session ID, returning True if it's valid.

    The server uses this function to check whether a session ID
    was generated with the correct secret key. If signed sessions are disabled,
    this function always returns True.

    Args:
        session_id (str) : The session ID to check
        secret_key (str, optional) : Secret key (default: value of 'BOKEH_SECRET_KEY' env var)
        signed (bool, optional) : Whether to check anything (default: value of
                                  'BOKEH_SIGN_SESSIONS' env var)

    """
    secret_key = _ensure_bytes(secret_key)
    if signed:
        pieces = session_id.split('-', 1)
        if len(pieces) != 2:
            return False
        base_id = pieces[0]
        provided_signature = pieces[1]
        expected_signature = _signature(base_id, secret_key)
        # hmac.compare_digest() uses a string compare algorithm that doesn't
        # short-circuit so we don't allow timing analysis
        return hmac.compare_digest(expected_signature, provided_signature)
    return True

#-----------------------------------------------------------------------------
# Dev API
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Private API
#-----------------------------------------------------------------------------

def _get_sysrandom() -> Tuple[Any, bool]:
    # Use the system PRNG for session id generation (if possible)
    # NOTE: secure random string generation implementation is adapted
    #       from the Django project. Reference:
    #       https://github.com/django/django/blob/0ed7d155635da9f79d4dd67e4889087d3673c6da/django/utils/crypto.py
    import random
    try:
        sysrandom = random.SystemRandom()
        using_sysrandom = True
        return sysrandom, using_sysrandom
    except NotImplementedError:
        import warnings
        warnings.warn('A secure pseudo-random number generator is not available '
                      'on your system. Falling back to Mersenne Twister.')
        if settings.secret_key() is None:
            warnings.warn('A secure pseudo-random number generator is not available '
                          'and no BOKEH_SECRET_KEY has been set. '
                          'Setting a secret key will mitigate the lack of a secure generator.')
        using_sysrandom = False
        return random, using_sysrandom

def _ensure_bytes(secret_key: Union[str, bytes, None]) -> Optional[bytes]:
    if secret_key is None:
        return None
    elif isinstance(secret_key, bytes):
        return secret_key
    else:
        return codecs.encode(secret_key, 'utf-8')

# this is broken out for unit testability
def _reseed_if_needed(using_sysrandom: bool, secret_key: Optional[bytes]) -> None:
    secret_key = _ensure_bytes(secret_key)
    if not using_sysrandom:
        # This is ugly, and a hack, but it makes things better than
        # the alternative of predictability. This re-seeds the PRNG
        # using a value that is hard for an attacker to predict, every
        # time a random string is required. This may change the
        # properties of the chosen random sequence slightly, but this
        # is better than absolute predictability.
        data = f"{random.getstate()}{time.time()}{secret_key!s}".encode('utf-8')
        random.seed(hashlib.sha256(data).digest())

def _base64_encode(decoded: Union[bytes, str]) -> str:
    # base64 encode both takes and returns bytes, we want to work with strings.
    # If 'decoded' isn't bytes already, assume it's utf-8
    decoded_as_bytes = _ensure_bytes(decoded)
    # TODO: urlsafe_b64encode only accepts bytes input, not Optional[bytes].
    # Perhaps we can change _ensure_bytes change return type from Optional[bytes] to bytes
    encoded = codecs.decode(base64.urlsafe_b64encode(decoded_as_bytes), 'ascii')  # type: ignore
    # remove padding '=' chars that cause trouble
    return str(encoded.rstrip('='))

def _signature(base_id: str, secret_key: Optional[bytes]) -> str:
    secret_key = _ensure_bytes(secret_key)
    base_id_encoded = codecs.encode(base_id, "utf-8")
    signer = hmac.new(secret_key, base_id_encoded, hashlib.sha256)  # type: ignore
    return _base64_encode(signer.digest())

def _get_random_string(length: int = 44,
                       allowed_chars: str = 'abcdefghijklmnopqrstuvwxyz'
                       'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                       secret_key: Optional[bytes] = settings.secret_key_bytes()) -> str:
    """
    Return a securely generated random string.
    With the a-z, A-Z, 0-9 character set:
    Length 12 is a 71-bit value. log_2((26+26+10)^12) =~ 71
    Length 44 is a 261-bit value. log_2((26+26+10)^44) = 261
    """
    secret_key = _ensure_bytes(secret_key)
    _reseed_if_needed(using_sysrandom, secret_key)
    return ''.join(random.choice(allowed_chars) for i in range(length))

#-----------------------------------------------------------------------------
# Code
#-----------------------------------------------------------------------------

random, using_sysrandom = _get_sysrandom()
