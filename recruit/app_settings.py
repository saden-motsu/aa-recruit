"""App Settings"""

# Django
from django.conf import settings

# Alliance IDs belonging to your coalition (e.g. The Imperium).
# Interactions with members of these alliances are treated as familiar/low priority.
RECRUIT_ALLY_ALLIANCE_IDS: frozenset[int] = frozenset(
    getattr(settings, "RECRUIT_ALLY_ALLIANCE_IDS", [
        1900696668,  # The Initiatvie.
        1354830081,  # [CONDI] Goonswarm Federation
        99009163,    # [D.C] Dracarys.
        99003214,    # [BRAVE] Brave Collective
        99010079,    # [BRUVE] Brave United
        99011223,    # [5IGMA] Sigma Grindset
        99003995,    # [IGC] Invidia Gloriae Comes
        99010877,    # [VAPOR] Out of the Blue.
        131511956,   # [TNT] Tactical Narcotics Team
        99011239,    # [L1GMA] Ligma Grindset
        99012042,    # [FNT] Fanatic Legion.
        99001969,    # [.S0B.] SONS of BANE
        99008165,    # [YM.CA] Young Miners Christian Association
        99009331,    # [SCUM] Scumlords
        99012849,    # [INVI] Invidia consilium perdit
    ])
)

# Alliance IDs of hostile coalitions (e.g. Winter Coalition).
# Interactions with members of these alliances are flagged as high priority.
RECRUIT_ENEMY_ALLIANCE_IDS: frozenset[int] = frozenset(
    getattr(settings, "RECRUIT_ENEMY_ALLIANCE_IDS", [
        99003581,    # [FRT] Fraternity.
        99013537,    # [EVIL.] Insidious.
        99009129,    # [NO] No Visual
        1727758877,  # [NC] Northern Coalition.
        386292982,   # [-10.0] Pandemic Legion
        99007203,    # [SB-SQ] Siberian Squads
        1042504553,  # [SLYCE] Solyaris Chtonium
        99002685,    # [SYN] Synergy of Steel
        498125261,   # [TEST] Test Alliance Please Ignore
    ])
)
