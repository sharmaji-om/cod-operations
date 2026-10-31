# AI Usage Log

## 1. Which AI tools did I use?

I used ChatGPT during this assignment.

I mainly used ChatGPT to brainstorm the business problem, understand the trade-offs and come up with the decision rules.


## 2. How did I use AI?

I did not directly start by building the application. First, I tried to understand what the actual problem was.

The main question was how to reduce COD returns without losing genuine customers.

I used ChatGPT to discuss different approaches, calculate the financial impact of returns and decide when an order should be shipped, confirmed, offered prepaid or rejected.

After deciding the rules, I used Claude to implement them and build the application.

AI also helped with writing tests, checking edge cases and improving the dashboard.

## 3. Where did I correct AI?

**Correction 1: Rejecting repeat customers**

Initially, the rejection rule was interpreted as rejecting every repeat customer with a trust score of minus 2 or lower.

I corrected this because a customer might have previous successful deliveries even with a negative score.

So I changed the rule to reject only when the trust score is minus 2 or lower and the customer has zero previous successful deliveries. Otherwise, the customer should get a chance to confirm.

**Correction 2: Looking only at RTO savings**

During planning, we initially focused on how much money could be saved by preventing RTOs.

But I wanted to consider the other side as well. If we stop a genuine customer from ordering, we also lose the margin from that order.

So we included both avoided RTO costs and lost genuine-order margin in the financial calculation.

**Correction 3: Making decisions for new customers**

One important decision was not to automatically reject new customers just because their predicted RTO probability was high.

We decided to give them an option to switch to prepaid with a small discount. Even if they decline prepaid, they can still confirm their COD order.

This was important because new customers have no previous order history, and a high predicted risk does not necessarily mean they are not genuine.

## 4. What did I learn?

The biggest thing I learned was that AI can help implement things quickly, but it still needs clear instructions and business reasoning.

If the rules are not properly defined, AI might build something that works technically but does not make sense for the business.

So I focused on understanding the problem, deciding the rules and reviewing the results before moving to the next part.