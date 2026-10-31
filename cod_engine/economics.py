def estimates(value, p, cfg):
    margin, loss = cfg.gross_margin * value, cfg.rto_loss
    denominator = cfg.confirmation_prevention * loss + cfg.confirmation_genuine_loss * margin
    threshold = (cfg.confirmation_genuine_loss * margin + cfg.message_cost) / denominator if denominator else None
    discount = min(cfg.discount_fraction * value, cfg.discount_cap)
    return {
        "delivered_contribution": margin, "rto_loss": loss,
        "expected_cod_contribution": (1-p)*margin-p*loss,
        "incremental_confirmation_contribution": p*cfg.confirmation_prevention*loss-(1-p)*cfg.confirmation_genuine_loss*margin-cfg.message_cost,
        "confirmation_break_even_probability": threshold,
        "discount": discount,
        "expected_converted_prepaid_contribution": (1-cfg.converted_prepaid_rto)*(margin-discount)-cfg.converted_prepaid_rto*loss,
        "assumptions": {"a": cfg.confirmation_prevention, "b": cfg.confirmation_genuine_loss, "message_cost": cfg.message_cost,
                        "gross_margin": cfg.gross_margin, "converted_prepaid_rto": cfg.converted_prepaid_rto,
                        "discount_basis": "delivered converted prepaid orders only", "acquisition_cost": "sunk; excluded",
                        "causal_effects": "illustrative assumptions, not measured"},
    }
