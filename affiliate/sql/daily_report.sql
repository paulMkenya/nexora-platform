(SELECT
    COALESCE(cl.day, cv.day),
    COALESCE(cl.clicks, 0),
    COALESCE(cv.total_qty, 0),
    COALESCE(cv.approved_qty, 0),
    COALESCE(cv.hold_qty, 0),
    COALESCE(cv.rejected_qty, 0),
    COALESCE(
        case cl.clicks
            when 0 then 0  -- avoid division by zero
            -- ::numeric before dividing: both operands are integers, so plain
            -- division truncates and 2 conversions on 300 clicks reads as 0%.
            else round(100.0 * cv.total_qty / cl.clicks, 2)
        end
        , 0) AS cr,
    COALESCE(cv.total_payout, 0),
    COALESCE(cv.approved_payout, 0),
    COALESCE(cv.hold_payout, 0),
    COALESCE(cv.rejected_payout, 0)
FROM
    (
        SELECT
            created_at::date AS day,
            count(*) AS clicks
        FROM tracker_click
        WHERE
            affiliate_id = {user_id}
            AND created_at between '{start_date}' AND '{end_date}'
            {offer_filter_clause}
        GROUP BY day
    ) AS cl
FULL OUTER JOIN
    (
        SELECT
            created_at::date AS day,
            count(*)                                       AS total_qty,
            count(*)    FILTER (WHERE status = 'approved') AS approved_qty,
            count(*)    FILTER (WHERE status = 'hold')     AS hold_qty,
            count(*)    FILTER (WHERE status = 'rejected') AS rejected_qty,
            sum(payout)                                    AS total_payout,
            sum(payout) FILTER (WHERE status = 'approved') AS approved_payout,
            sum(payout) FILTER (WHERE status = 'hold')     AS hold_payout,
            sum(payout) FILTER (WHERE status = 'rejected') AS rejected_payout
        FROM tracker_conversion
        WHERE
            affiliate_id = {user_id}
            AND created_at between '{start_date}' AND '{end_date}'
            {offer_filter_clause}
        GROUP BY day
    ) AS cv
ON cl.day = cv.day
-- Order on the same COALESCE the SELECT displays. This is a FULL OUTER JOIN,
-- so a day with conversions but no clicks has cl.day = NULL, and ordering by
-- cl.day alone sorted those rows to the top (NULLS FIRST on DESC) regardless
-- of their real date.
ORDER BY COALESCE(cl.day, cv.day) DESC)
;