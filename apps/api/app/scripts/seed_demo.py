from datetime import date

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.company import CompanyCustomsRelation, CompanyMaster
from app.models.contact import CompanyContactRelation, ContactMaster
from app.models.customs import CustomsRecord


def seed() -> None:
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        if db.query(CompanyMaster).count() > 0:
            print("Seed skipped: company_master already has data.")
            return

        company1 = CompanyMaster(
            standard_name="Bavaria Precision Manufacturing GmbH",
            country="Germany",
            city="Munich",
            website="https://www.bavaria-precision.example",
            domain="bavaria-precision.example",
            industry="Sheet Metal Fabrication",
            keywords_text="laser cutting machine,sheet metal fabrication,industrial machinery,wholesale,low moq,restock",
            description="German manufacturer focused on laser cutting and precision sheet metal components, supporting low MOQ, trial orders and wholesale restock.",
            confidence_level="A",
            confidence_score=0.92,
        )
        company2 = CompanyMaster(
            standard_name="Nordic Industrial Systems AB",
            country="Germany",
            city="Hamburg",
            website="https://www.nordic-industrial.example",
            domain="nordic-industrial.example",
            industry="Industrial Equipment",
            keywords_text="laser equipment,industrial systems,cutting automation,reseller,distributor,small batch",
            description="Industrial systems integrator importing cutting and fabrication equipment for distributors and small batch buyers.",
            confidence_level="B",
            confidence_score=0.83,
        )

        contact1 = ContactMaster(
            full_name="Anna Keller",
            job_title="Procurement Manager",
            email="anna.keller@bavaria-precision.example",
            email_type="business",
            confidence_level="A",
        )
        contact2 = ContactMaster(
            full_name="Lars Becker",
            job_title="Head of Supply Chain",
            email="l.becker@nordic-industrial.example",
            email_type="business",
            confidence_level="B",
        )

        customs1 = CustomsRecord(
            subject_name="Bavaria Precision Manufacturing GmbH",
            trade_direction="import",
            hs_code="845611",
            product_description="Laser cutting machines and accessories",
            trade_date=date(2026, 3, 18),
            trade_frequency=14,
            active_label="最近 12 个月持续进口",
        )
        customs2 = CustomsRecord(
            subject_name="Nordic Industrial Systems AB",
            trade_direction="import",
            hs_code="845611",
            product_description="Industrial cutting equipment",
            trade_date=date(2026, 2, 27),
            trade_frequency=8,
            active_label="最近 6 个月活跃",
        )

        db.add_all([company1, company2, contact1, contact2, customs1, customs2])
        db.flush()

        db.add_all(
            [
                CompanyContactRelation(company_id=company1.id, contact_id=contact1.id, priority_rank=1),
                CompanyContactRelation(company_id=company2.id, contact_id=contact2.id, priority_rank=1),
                CompanyCustomsRelation(company_id=company1.id, customs_record_id=customs1.id, match_confidence="A"),
                CompanyCustomsRelation(company_id=company2.id, customs_record_id=customs2.id, match_confidence="B"),
            ]
        )

        db.commit()
        print("Seed completed.")


if __name__ == "__main__":
    seed()
