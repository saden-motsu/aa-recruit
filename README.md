# aa-recruit

An [Alliance Auth](https://allianceauth.readthedocs.io/) plugin for evaluating recruit applications. It aggregates interaction history for a user's characters — contacts, mails, contracts, wallet transactions — and groups them by the external character involved, showing corp/alliance history alongside the events.

## Features

- Character Selector
    - Lists `Main Character Name (User State)`, sorted by more recent user registration first.
    - By default selects the user most recently 
- Links to GICE Blacklist and EVE411 for quick lookups
- Groups all character events / interactions by external entity
    - A character interatcion is any ESI item which is associated with a character other than the recruit.
    - Interactions between alts are removed.
- External Character Corp History
    - For an external character show their corporation membership. Separates out time blocks for when the corporation changes alliance.
- Groups location events / interactions by region / constellation / system / station as applicable.
    - For example, mining ledger entries only have associated system information. You can't mine in stations.
    - Assets always have a station associated, since ESI doesn't give information about assets in space.
- Stations contain a clones list, which includes the current clone, any supplimental clones that can be jumped to, and any characters for which the station is listed as their home station.
- Station assets are listed by most to least expensive. 

## Dependencies

- Alliance Auth >= 4.3.1 < 5.0
- [Member Audit](https://gitlab.com/allianceauth/allianceauth)
    - Provides character data and the `finder_access` permission
- [Eve Universe](https://apps.allianceauth.org/apps/detail/django-eveuniverse)
    - A dependency of Member Audit, and types used by many of the native data types.
    - Also used locally to query ESI endpoints.

## Permissions

The `memberaudit.finder_access` permission is re-used to allow access to the recruit tool.
The core of the data provided by the application is a duplicate of what is already
available through the Member Audit tool, just repackaged and restructured.

## TODOs
- Corp history for recruit characters
- Implement a priority system.
    - Most of the data we have is noise. Something like a traffic light system, or literal red flag (🚩) could help recruiters decide on what to focus on.
    - Interactions with characters currently in enemy groups is more suspicious than current corp members.
    - Mining in hostile sov. null is different than mining near Jita.
    - On the backend this should just be tracked as a number between 0-1. Fuzzy logic can be used to combine factors. Rendering thresholds should be independent.
    - This should be encorpreated into sorting.

- Lightweight home page that lists non-member users and their current auth state. Links to their recruit page.
    - Flag users with characters not registered with alliance auth.
    - List discord ID for synced characters.
    - Flag users with characters not registered with alliance auth.

- Location Grouped Events
    - Make the clones list in stations a detail object.
    - Assets lack a quantity indicator.
    - Assets should load the relevant icons images.
    - Asset hierarchy should be respected. Containers and ships should allow items to be broken out.
    - Ships should include the ship name as well as the hull type.
    - Stations, systems, constellations, & regions should include some metadata at the top level.
        - Total asset value.
        - Total asset safety wraps.
        - Clone count.
        - Contract total.
- Soverignty
    - Systems should have soverignty listed.
    - Constellations & Regions should list plurality ownership.
- Integrate killboard data.
    - By default killboards will generate too much noise.
    - Prioritization must come first.
    - Every character that a player has everfought with or against is too much data to be useful.
    - More useful is to track killboard information for characters that have other associated metadata.
