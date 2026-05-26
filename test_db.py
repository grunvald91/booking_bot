"""Test database and basic functions"""
import asyncio
import sys

async def test():
    print("=== Testing database ===")

    try:
        from database import async_session_maker, init_db
        from database.crud import get_all_active_businesses, get_business_by_id, get_business_services

        # Init DB
        await init_db()
        print("OK: Database initialized")

        # Get all businesses
        async with async_session_maker() as session:
            businesses = await get_all_active_businesses(session)
            print(f"OK: Found {len(businesses)} businesses")

            if businesses:
                for b in businesses:
                    print(f"  - Business ID={b.id}, name={b.name}")

                # Check first business
                first_business = businesses[0]
                business = await get_business_by_id(session, first_business.id)
                if business:
                    print(f"OK: get_business_by_id({first_business.id}) = {business.name}")
                else:
                    print(f"ERROR: get_business_by_id({first_business.id}) returned None!")

                # Check services
                services = await get_business_services(session, first_business.id)
                print(f"OK: Found {len(services)} services for business {first_business.id}")
                for s in services:
                    print(f"  - Service ID={s.id}, name={s.name}")
            else:
                print("WARNING: No businesses found in database!")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n=== All tests passed ===")
    return 0

if __name__ == "__main__":
    result = asyncio.run(test())
    sys.exit(result)
