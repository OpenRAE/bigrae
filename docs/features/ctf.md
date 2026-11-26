# CTF

Use this guide to join an event, work in your assigned range, and submit flags.
Your organizer supplies the exercise rules and authorized targets.

## Joining an event

An optional public registration page accepts a request for organizer review.
It does not create an account, reserve capacity, or provision a range.
A duplicate request receives the same generic confirmation.
If the page is unavailable, contact the organizer.

After approval:

1. Open the dedicated CTF login URL supplied by your organizer.
2. Enter the temporary username and initial password through that page.
3. Choose a new password when prompted before opening other CTF pages.
4. Read the event state and time remaining on the dashboard.

A registration email contains event details, not a password.
Mail requires a configured provider.
Temporary CTF credentials work only on participant CTF pages.
Normal platform credentials use the separate platform login.
Access ends at event end; anonymization follows the configured retention window.

To set reminder time zone, open **Account** and enter an IANA value, such as `Europe/Paris`.
Select **Use** for the browser time zone, or leave the field blank for the event time zone.

## Briefing

Open **Briefing** when the organizer publishes one.
It gives event-specific orientation and starting points.
Without a briefing, use the standard help and organizer instructions.

## Your range

1. Open **Range** to inspect provisioning and access details.
2. Wait for the assigned range to become ready.
3. Use [Terminal](terminal.md) for the supported guest channels.
4. Use **Download VPN profile** only when the ready range advertises that capability.

Keep an `.ovpn` profile private.
Remove the local copy after the event.
The platform provisions event ranges; participants do not launch or destroy them through Mission Control.
Ask the organizer for recovery when a range fails.
Event cleanup follows the organizer's configured lifecycle.

## Challenges

Open **Challenges** and select an available challenge.
Read its description, category, points, difficulty, target, and current state.

To change the list:

1. Select **By category**, **By status**, or **All** to change the view.
   **By status** shows **Not solved**, then **Solved**.
2. Select **Cards**, **List**, or **Table** to change the layout.
   The layout does not change the order of the challenges.
3. Select a key in **Sort within groups** to sort the challenges in each group.
4. Select a tag or topic to show only the challenges that have it.
   Select it again to remove the filter.

A challenge that a teammate solved counts as solved.
The page keeps these selections when you open a challenge and go back.

On a challenge page, select **Previous** or **Next** to open the adjacent challenge.
The buttons follow the order of the list, with your view, sort, and filter.
The default order is **Start Here**, then the missions in number order.
A button is disabled at the start or the end of the list.
Scheduled releases and prerequisites can keep other challenges locked.
Use only targets within the event's authorization.

## Submitting flags

1. Recover the flag through the authorized challenge steps.
2. Enter it in the challenge submission form.
3. Submit it and read the result.

The server validates submissions against the configured flag type.
Static flag values are stored as normalized plaintext; they are not protected by a one-way hash.
Organizers must protect authoring access and exports accordingly.
The challenge can enforce a cooldown and attempt limit.
A repeated correct submission does not award the same solve twice.

Open **Account** to see each flag that you submitted correctly and its challenge.
The list shows only your own flags, not the flags of teammates.

## Hints

Read the displayed cost before revealing a hint.
A hint can reduce the score for that challenge.

## Teams and brackets

In team mode, you can join or create a team to share a score.
A participant with no team competes as an individual and can still submit flags and score.
The event's team-size limit applies to teams.
Solo events require no team membership.

The challenge list and the challenge page show a challenge that a teammate solved as **Solved by** *name*.
The name is the current team member who solved it first.
You can still submit the flag for your individual score.

Brackets provide separate cohort standings when the organizer uses them.

## Challenge statistics

The challenge page shows per-challenge statistics when the organizer enables them for the event.
The statistics are the solve count, the solve rate, the attempt count, and the first solver's name.
The statistics refresh while the page is open.
The page hides the statistics when the organizer does not enable them.

A captain can rename the team, remove members, and transfer captaincy.
Disbanding requires the current members to have no recorded correct solve.
A zero-point solve still prevents disbanding.
The same rule applies when the last member leaves.

## Scoreboard

Open **Scoreboard** for the permitted standings.
In a team-mode event, open **Individual scoreboard** for participant standings.
Open **Team scoreboard** for team standings.
An open scoreboard refreshes every **15 seconds**.

A graph above the table shows the score over time of the top eight entries.
Open **Score history** below the graph to read each time and score as a table.
The graph shows times and scores only, not challenge names.

To change the board:

1. Type a name in **Filter participants** or **Filter teams** to show only the matching entries.
2. Select a key in **Sort by** to change the order.
   **Rank** gives the official order.

The rank column always shows the official rank.
The filter and the sort apply to the selected bracket.
They do not change the graph.

The organizer can hide it or freeze results near event end.
Do not infer final standings from a frozen display.

See [participant messages](ctf-communications.md#participant-inbox) for event notices.
See the [organizer guide](ctf-organizer-guide.md) for event administration and the [CTF reference](../technical/shifter_platform/ctf.md) for contracts.
