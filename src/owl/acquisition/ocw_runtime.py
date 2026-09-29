"""Explicit, source-pinned removal of two noninstructional OCW startup calls."""
import hashlib

from ..safety import SafetyError


POLICY = 'native-media-no-telemetry-v1'
MEMBER = 'static_shared/js/course_offline.21a26.js'
SOURCE_SHA256 = 'b2de542cee6224c44041e26482ffdd0f22d7811a16bd3924af757e23595f1020'
YOUTUBE = '"undefined"!=typeof document&&(s("https://www.youtube.com/iframe_api",r),a())'
SENTRY = 't.Ts({release:"1.159.0",dsn:"https://eee58f41dda54d2b814296e12dced4b7@o48788.ingest.sentry.io/5304953",environment:"production"})'


def policy_for_inventory(inventory):
    rows = [row for row in inventory['members'] if row['path'] == MEMBER]
    if len(rows) != 1 or rows[0]['sha256'] != SOURCE_SHA256:
        raise SafetyError('Course runtime differs from the exactly reviewed publisher bundle')
    return {MEMBER: {'policy': POLICY, 'source_sha256': SOURCE_SHA256}}


def localize_runtime(data, member, policy):
    if (member != MEMBER or policy != {'policy': POLICY, 'source_sha256': SOURCE_SHA256}
            or hashlib.sha256(data).hexdigest() != SOURCE_SHA256):
        raise SafetyError('OCW runtime policy is not bound to its exactly reviewed source')
    text = data.decode('utf-8')
    if text.count(YOUTUBE) != 1 or text.count(SENTRY) != 1:
        raise SafetyError('OCW runtime startup calls differ from reviewed exact spans')
    # Keep YouTube tech definitions and its callback registration; local native
    # video replaces the remote API. Keep the Sentry namespace but never start
    # its telemetry client. Navigation and every other bundle byte are retained.
    return text.replace(YOUTUBE, '"undefined"!=typeof document&&a()').replace(SENTRY, 'void 0').encode('utf-8')
