# Prices, discounts and badges

## Money

Prices are stored as integers in minor units (kopecks) in columns ending in `_minor`, so no rounding errors creep in. The API returns whole hryvnias (`*_minor / 100`, rounded half up), and the UI formats them the Ukrainian way, for example `17 899` followed by the hryvnia sign.

## Discounts

| Value | Definition |
|---|---|
| Discount | `100 * (1 - price / regular price)` in whole percent, rounded the way the shop rounds its own badges: truncated for PRM and Answear.ua (48.5% is -48%), rounded half up for Footshop (9.99% is -10%). |
| Honest discount | the same formula against the lowest price of the last 30 days, when the shop reports one that is higher than the current price; otherwise empty. It shows whether a sale price is really lower than the recent normal price. |
| Savings | regular price minus current price. |

The catalog sorts by discount, biggest first, and breaks ties by bigger savings. Other sorts: honest discount, savings, price (both directions) and newest. Items without an honest discount come last in that sort.

## Price history

The history is a change log: a row is written when an item is first seen and whenever its price, regular price or 30-day lowest price changes. Runs that see the same prices add nothing. The item drawer draws this log as a chart.

The current state of every item is also kept on the item itself (price, discount, previous price, the run of the last change), so lists and filters never need the history table.

## In the sale or not

An item is **active** while it is in the sale. It becomes inactive only after two successful runs in a row did not see it: the shop's API sometimes orders equal items differently between requests, so a single run can miss a few items, and one miss should not remove them. Partial, failed and cancelled runs never deactivate anything. An item that shows up again becomes active again.

Inactive items disappear from the catalog but stay in favorites, marked "Not in sale".

## Badges

Badges compare the latest finished run of a shop with the one before it.

| Badge | Shown when |
|---|---|
| **NEW** | the item was first seen in the shop's latest finished run, and the shop had an earlier run (the very first run marks nothing as new) |
| **cheaper** | the item's price changed in the shop's latest finished run and went down; hovering shows the previous price |

The sidebar filters **New since last run** and **Got cheaper** use the same definitions.

## Sizes

Every size of an item is stored with the shop's availability. `IN_STOCK` and `LAST` count as in stock; other values do not. Footshop lists only the sizes that can be bought, so all of its listed sizes count as in stock. The size filter and **Only my sizes** match sizes in stock only. Saved sizes are compared by label (for example `M`, `43`, `W32`) and are highlighted on the cards.

## Favorites

Starring an item records the price at that moment. The Favorites page shows the change since then (negative means cheaper) and keeps items that left the sale.
