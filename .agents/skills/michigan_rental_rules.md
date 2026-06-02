# Agent Skill: Michigan Rental Property & IRS Pub 925 Rules

This skill defines the tax rules, validation logic, and regulatory references for handling residential rental properties, specifically focusing on passive activity limits and depreciation under a high-income profile.

## 1. IRS Pub 925: Passive Activity & At-Risk Rules

### At-Risk Rules (IRC § 465)
Before applying passive loss rules, the taxpayer's loss must clear the at-risk limitations.
- Taxpayers are generally at risk for the amount of cash and the adjusted basis of property contributed to the activity, plus any amounts borrowed for use in the activity for which they are personally liable or have pledged property as security.
- **Qualified Nonrecourse Financing:** For real estate, qualified nonrecourse financing secured by the real property is treated as an amount at risk.

### Passive Activity Loss (PAL) Limitations (IRC § 469)
Rental real estate is per se a passive activity regardless of the taxpayer's level of participation (unless they qualify as a Real Estate Professional under IRC § 469(c)(7)).

#### The $25,000 Special Allowance Phase-Out
- **General Rule:** Taxpayers who "actively participate" in a rental real estate activity can deduct up to $25,000 of passive rental losses against non-passive income (such as W-2 wages, interest, and business profits).
- **Phase-Out Formula:** The $25,000 allowance is reduced by $0.50 for every $1.00 that the taxpayer's Modified Adjusted Gross Income (MAGI) exceeds $100,000.
  $$\text{Allowance Reduction} = (\text{MAGI} - \$100,000) \times 0.50$$
- **Complete Phase-Out Threshold:** The allowance is reduced to $0 when MAGI reaches **$150,000**. Once MAGI exceeds $150,000, 100% of rental losses must be suspended and carried forward.

#### Loss Suspension & Form 8582
- All passive rental losses must be suspended and carried forward to the subsequent tax year.
- Suspended losses are tracked and reported on **IRS Form 8582** (Passive Activity Loss Limitations).
- Suspended losses can be offset against passive income in future years or fully deducted in the year the taxpayer disposes of their entire interest in the activity to an unrelated party in a fully taxable transaction.

---

## 2. MACRS Depreciation Rules (IRS Pub 946)

For residential rental property, depreciation must be calculated using the Modified Accelerated Cost Recovery System (MACRS).

### Key Parameters
- **Property Class:** Residential Rental Property.
- **Recovery Period:** **27.5 years** under the General Depreciation System (GDS). (Alternative Depreciation System [ADS] is 30 years if elected or required).
- **Depreciation Method:** **Straight-Line**.
- **Convention:** **Mid-Month**. The property is treated as placed in service (or disposed of) in the middle of the month, regardless of the actual date.

### Depreciation Basis Formula
$$\text{Depreciable Basis} = \text{Purchase Price} + \text{Acquisition Costs} - \text{Land Value}$$
> [!IMPORTANT]
> Land is NOT depreciable. The Audit Agent must verify that the land value was properly carved out of the depreciable basis.

---

## 3. Michigan State Specific Rules (Michigan Form 5082 / Schedule 1)

- **Federal/State Alignment:** Michigan taxable income starts with Federal Adjusted Gross Income (AGI). 
- **State PAL Treatment:** Since federal passive activity loss rules apply, the rental losses suspended on Form 8582 are also suspended for Michigan state income tax. No separate Michigan state adjustment is made for current-year suspended losses.
- **Property Taxes & Expenses:** Michigan rental expenses (including property taxes paid to the local municipality) are deducted on Schedule E to arrive at federal net rental income/loss, which flows into federal AGI. No double deduction is allowed on the Michigan state return.

---

## 4. Tax Planning & Minimization Loopholes (Aggressive Strategies)

### Strategy A: The Short-Term Rental (STR) Loophole (Treas. Reg. § 1.469-1T(e)(3)(ii)(A))
If the property is rented as a short-term rental rather than a long-term residential rental:
- **Definition:** The average period of customer use is **7 days or less**.
- **Result:** The activity is NOT considered a "rental activity" under IRC § 469.
- **Material Participation Requirement:** To deduct losses against W-2 income, the taxpayer must "materially participate" in the activity by meeting one of the IRS tests (typically, spending >100 hours on the activity and more than any other individual, or spending >500 hours).
- **Tax Benefit:** If they meet both requirements, the rental loss is classified as **active/non-passive**, allowing them to deduct the entire loss (including MACRS depreciation) against W-2 wages in the current tax year, bypassing the passive loss suspension rules.

### Strategy B: Real Estate Professional Status (REPS) Spouse Strategy (IRC § 469(c)(7))
A spouse who does not work full-time outside of real estate can qualify if they meet the following:
1. **750-Hour Test:** More than 750 hours of services are performed in real property trades or businesses (such as development, construction, acquisition, rental, management, operations, or leasing) during the tax year.
2. **50% Test:** More than 50% of their total personal services during the tax year are performed in these real property trades or businesses.
3. **Material Participation:** They must materially participate in each rental activity.
- **Tax Benefit:** If Spouse 2 qualifies as a Real Estate Professional, the rental activities are treated as active, and all rental losses are fully deductible against W-2 income.
