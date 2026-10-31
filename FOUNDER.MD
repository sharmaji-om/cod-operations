# Founder Memo
**Root & Ritual | COD Risk Management**

## 1. What problem are we trying to solve?

Our main problem is COD returns. Currently, around 28% of COD orders are returned, and each return costs us approximately ₹169.40. But we cannot simply cancel every order that looks risky because we might lose genuine customers, especially new customers who are coming through paid marketing.

So the idea is simple. Instead of treating every COD order the same, we look at the customer's previous orders, delivery address, acquisition source and estimated RTO probability. Based on these, we decide whether to ship directly, ask for WhatsApp confirmation, offer prepaid with a small discount, or hold the order.

The goal is not to reduce RTO at any cost. It is to reduce RTO while protecting genuine orders and our overall contribution.

## 2. What did we find in the data?

We started with 2,018 historical orders. After cleaning the data and excluding duplicate orders and invalid records, we had 1,950 orders for evaluation.

Here are three important things we found.

**First, the acquisition source matters.** Meta ads had an RTO rate of 31.15%, while direct orders had an RTO rate of 22.89%. This is a difference of around 8 percentage points. So acquisition source is useful for estimating risk, although it should never be the only reason to reject an order.

**Second, not every order has the same risk.** In our test set, orders selected for direct shipping had an actual historical RTO rate of 18.33%, while orders selected for WhatsApp confirmation had a rate of 24.62%. This tells us that the engine is separating some lower risk orders from higher risk ones.

**Third, holding orders is not always profitable.** The hold or cancel group had a historical RTO rate of 70%. That sounds good for identifying risky orders, but the remaining 30% were genuine delivered orders. If we hold these orders without giving customers a way to correct their details, we might lose revenue unnecessarily.

We also trained a logistic regression model to estimate RTO probability. It achieved an AUC of 0.694 on the test set. This is useful for prioritizing orders, but it is not accurate enough to make every decision automatically without business rules.

## 3. What rules did we choose?

For repeat customers, we use their previous delivery history.

We calculate a trust score by subtracting previous RTOs from successful deliveries.

If the score is 2 or more, we ship directly. If the score is 0 or 1, we use the predicted risk and financial calculation to decide whether confirmation is needed.

If the score is negative, we require WhatsApp confirmation. We only reject a repeat customer when the score is minus 2 or lower and they have never had a successful delivery.

For new customers, we are more careful about rejection. We do not reject them simply because the model predicts high risk. If their estimated RTO probability is above 40%, we offer a 5% prepaid discount capped at ₹50. If they decline prepaid, they can still confirm their COD order through WhatsApp.

For other new customers, we use the financial calculation to decide whether confirmation is worth it.

We also hold orders with unusable addresses for correction instead of immediately cancelling them.

## 4. What happened in our backtest?

We tested the engine on 412 later historical orders that were not used for training.

The decisions were:

| Decision | Orders |
|---|---:|
| Ship directly | 120 |
| WhatsApp confirmation | 260 |
| Prepaid nudge | 2 |
| Hold or cancel | 30 |

For the financial simulation, we assumed that WhatsApp confirmation prevents 50% of RTOs, loses 3% of genuine orders and costs ₹1 per confirmation episode. We also assumed 30% prepaid offer acceptance.

Under these assumptions, the estimated result was:

| Financial impact | Amount |
|---|---:|
| RTO cost avoided | ₹9,084.24 |
| Net foregone delivered margin | ₹8,757.61 |
| Messaging cost | ₹263.40 |
| Discount cost | ₹17.24 |
| **Net improvement** | **₹45.99** |

The improvement is very small. In fact, when we tested the September orders separately, the same assumptions gave an estimated loss of ₹609.26.

I think this is an important finding. It shows that reducing RTO does not automatically mean improving profit. If our confirmation process causes too many genuine customers to drop out, the money saved from RTO can easily be lost.

These are simulated results, not actual savings. We do not have historical WhatsApp responses or prepaid conversion data, so we cannot claim that these interventions would have produced the same results in reality.

## 5. Operations vs Marketing

Operations would prefer cancelling more risky orders because every RTO costs money.

Marketing has a different concern. The company already spends more than ₹300 to acquire customers through Meta ads, and rejecting a genuine new customer could mean losing both the current order and future purchases.

Our approach tries to balance both sides.

We use stricter rules for repeat customers with consistently unsuccessful delivery histories, but give new customers a chance to confirm or switch to prepaid.

The financial calculation also considers the margin we might lose from a genuine order, rather than looking only at the RTO cost.

## 6. What can go wrong?

The biggest risk is that our assumptions might be wrong. We assumed 50% RTO prevention and 3% genuine customer loss, but these numbers have not been measured.

The model can also make incorrect predictions, especially for customers or locations with limited historical data.

Another issue is address validation. An incomplete address does not necessarily mean a fake order. This is why the system should allow address correction.

WhatsApp messages might also go unanswered because customers are busy or miss the message. We should not automatically assume they were unwilling to receive the order.

Finally, the prepaid discount may not convince enough customers to switch. In our historical test, only two orders qualified for the prepaid nudge, so we do not have enough evidence to judge how effective that part of the strategy will be.

## 7. What would I do in the next two weeks?

**Week 1**

I would run a small pilot where some eligible orders follow the existing shipping process and others go through our decision engine.

I would track WhatsApp response rates, genuine orders lost, prepaid acceptance, address corrections and eventual RTO outcomes.

I would also review held orders manually to understand whether we are blocking genuine customers.

**Week 2**

I would compare the pilot groups using actual contribution, not just RTO percentage.

Based on the results, I would adjust the confirmation threshold, prepaid discount and hold rules. I would also check whether different acquisition sources need different handling.

I would not introduce automatic rejection for new customers until we have much stronger evidence.

## Final thought

The main thing I learned from this exercise is that identifying risky orders is only one part of the problem.

The harder part is deciding what action makes financial sense.

Our backtest shows that even when we identify higher risk orders, the benefit can disappear if we lose genuine customers. So I would treat this system as a starting point, measure its real impact through a controlled pilot and improve the rules based on actual customer behavior.