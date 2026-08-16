from http import HTTPStatus

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve, reverse

from helpdesk import settings as hd_settings
from helpdesk.models import Queue, Ticket

User = get_user_model()


class DashboardViewTests(TestCase):
    """
    Test suit for the main dashboard of the project.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        # Alice is our support staff handling all tickets
        cls.user = User.objects.create_user(
            username="alice",
            password="testpass123",
            email="alice@example.com",
            is_staff=True,
        )
        # Bob is another user who works with Alice
        cls.bob = User.objects.create_user(
            username="bob",
            password="testpass123",
            email="bob@example.com",
            is_staff=True,
        )

        # Alice provides support for products related problems
        cls.queue = Queue.objects.create(title="Products", slug="products")

        # We create 4 tickets of each type:
        # unassigned, assigned, closed & user created
        cls.unassigned_ticket = Ticket.objects.create(
            title="My product is faulty", queue=cls.queue
        )
        cls.assigned_ticket = Ticket.objects.create(
            title="My product is missing parts", queue=cls.queue, assigned_to=cls.user
        )
        cls.closed_ticket = Ticket.objects.create(
            title="Product shipment delayed",
            queue=cls.queue,
            status=hd_settings.CLOSED_STATUS,
            assigned_to=cls.user,
        )
        cls.created_ticket = Ticket.objects.create(
            title="User address is invalid",
            queue=cls.queue,
            submitter_email=cls.user.email,
            assigned_to=cls.user,
        )  # <-- user created and assigned to herself

        cls.url = reverse("helpdesk:dashboard")
        cls.template = "helpdesk/dashboard.html"

    def test_url_resolves_correct_view(self):
        match = resolve(self.url)
        self.assertEqual(match.url_name, "dashboard")

    def test_anonymous_user_cannot_access(self):
        # Arrange
        login_url = "{}?next={}".format(reverse("helpdesk:login"), self.url)

        # Act
        # Make an anonymous user directly access the dashboard url
        r = self.client.get(self.url)

        # Assert
        # User should be redirected to login screen
        self.assertEqual(r.status_code, HTTPStatus.FOUND)
        self.assertRedirects(r, login_url)
        self.assertTemplateNotUsed(self.template)

    def test_staff_user_can_access_dashboard(self):
        # Arrange: staff user logs in
        self.client.force_login(self.user)

        # Act
        r = self.client.get(self.url)

        # Assert
        self.assertEqual(r.status_code, HTTPStatus.OK)
        self.assertTemplateUsed(r, self.template)
        self.assertContains(r, "Dashboard")
        self.assertNotContains(r, "Hi I shoud not be here!")

        # Check basic kpi cards are present
        self.assertContains(r, "Work in progress")
        self.assertContains(r, "Open or Unassigned")
        self.assertContains(r, "Created or opened by me")
        self.assertContains(r, "Resolved or Closed")

    def test_tables_contains_correct_tickets(self):
        # Arrange: staff user logs in
        self.client.force_login(self.user)

        # Act
        r = self.client.get(self.url)

        # Assert
        # Remember that ctx queryset are actually paginator objects
        ctx = r.context

        assigned = ctx["assigned_tickets"].object_list
        unassigned = ctx["unassigned_tickets"].object_list
        created = ctx["created_tickets"].object_list
        closed = ctx["closed_tickets"].object_list

        self.assertEqual(set(assigned), {self.assigned_ticket, self.created_ticket})
        self.assertEqual(unassigned, [self.unassigned_ticket])
        self.assertEqual(created, [self.created_ticket])
        self.assertEqual(closed, [self.closed_ticket])

        self.assertEqual(len(assigned), 2)
        self.assertEqual(len(unassigned), 1)
        self.assertEqual(len(created), 1)
        self.assertEqual(len(closed), 1)

    def test_basic_system_kpi_stats_are_correct(self):
        """
        Here we check the top row of the dashboard which shows
        kpi stats for the entire system.
        """

        # Arrange: staff user logs in
        self.client.force_login(self.user)

        # Act
        r = self.client.get(self.url)

        # Assert
        open_ticket_stats = r.context["basic_ticket_stats"]["open_ticket_stats"]
        days_lt_30, days_30_to_60, days_gt_60 = open_ticket_stats

        # Remember we have 3 open and 1 closed within this month
        self.assertEqual(days_lt_30[0], "Tickets < 30 days")
        self.assertEqual(days_lt_30[1], 3)

        self.assertEqual(days_30_to_60[0], "Tickets 30 - 60 days")
        self.assertEqual(days_30_to_60[1], 0)

        self.assertEqual(days_gt_60[0], "Tickets > 60 days")
        self.assertEqual(days_gt_60[1], 0)

    def test_user_kpi_stats_are_correct(self):
        """
        Here we check the second row of the dashboard which shows
        kpi stats specific to a user.
        """

        # Arrange: staff user logs in
        self.client.force_login(self.user)

        # Act
        r = self.client.get(self.url)

        # Assert
        # User sees 2 assigned, 1 open, 1 closed, 1 created
        fragment = (
            '<span class="d-block">{n}</span><span class="text-secondary">{msg}</span>'
        )
        self.assertContains(r, fragment.format(n=2, msg="Work in progress"), html=True)
        self.assertContains(
            r, fragment.format(n=1, msg="Open or Unassigned"), html=True
        )
        self.assertContains(
            r, fragment.format(n=1, msg="Created or opened by me"), html=True
        )
        self.assertContains(
            r, fragment.format(n=1, msg="Resolved or Closed"), html=True
        )

    def test_user_sees_only_tickets_assigned_to_herself(self):
        # Arrange: create a ticket & assign it to bob
        bobs_ticket = Ticket.objects.create(
            title="Please cancel my order", queue=self.queue, assigned_to=self.bob
        )
        # Alices logs in
        self.client.force_login(self.user)

        # Act
        r = self.client.get(self.url)

        # Assert: alice doesn't see bob's ticket
        ctx = r.context

        assigned = ctx["assigned_tickets"].object_list
        unassigned = ctx["unassigned_tickets"].object_list
        created = ctx["created_tickets"].object_list
        closed = ctx["closed_tickets"].object_list

        self.assertNotIn(bobs_ticket, assigned)
        self.assertNotIn(bobs_ticket, unassigned)
        self.assertNotIn(bobs_ticket, created)
        self.assertNotIn(bobs_ticket, closed)

    def test_user_sees_only_tickets_closed_by_herself(self):
        # Arrange: create a ticket which is closed by bob
        bobs_closed_ticket = Ticket.objects.create(
            title="Please cancel my order",
            queue=self.queue,
            assigned_to=self.bob,
            status=hd_settings.CLOSED_STATUS,
        )
        # Alices logs in
        self.client.force_login(self.user)

        # Act
        r = self.client.get(self.url)

        # Assert: alice doesn't see bob's closed ticket
        ctx = r.context
        closed = ctx["closed_tickets"].object_list
        self.assertNotIn(bobs_closed_ticket, closed)

    def test_user_sees_only_tickets_created_by_herself(self):
        # Arrange: bob submits a new ticket
        bobs_created_ticket = Ticket.objects.create(
            title="Please cancel my order",
            queue=self.queue,
            assigned_to=self.bob,
            submitter_email=self.bob.email,
        )
        # Alices logs in
        self.client.force_login(self.user)

        # Act
        r = self.client.get(self.url)

        # Assert: alice doesn't see bob's created ticket
        ctx = r.context
        created = ctx["created_tickets"].object_list
        self.assertNotIn(bobs_created_ticket, created)

    def test_user_sees_all_unassigned_tickets(self):

        # Arrange: We create 2 new unassigned tickets
        # we already one unassigned ticket created in setup()
        # so in total we have 3 unassigned
        t1 = Ticket.objects.create(title="Bad shipment", queue=self.queue)
        t2 = Ticket.objects.create(title="Late order", queue=self.queue)

        self.client.force_login(self.user)

        # Act: Alice visits the dashboard
        r = self.client.get(self.url)

        # Assert: Alice see all 3 open tickets
        unassigned = r.context["unassigned_tickets"].object_list

        self.assertEqual(set(unassigned), {self.unassigned_ticket, t1, t2})
        self.assertEqual(len(unassigned), 3)

    def test_assigned_tickets_sort(self):
        # Arrange
        COLS = ("id", "priority", "status", "modified")
        self.client.force_login(self.user)

        # check ascending sorts
        for col in COLS:
            r = self.client.get(self.url + f"?ut_sort={col}")
            items = r.context["assigned_tickets"].object_list
            self.assertLessEqual(getattr(items[0], col), getattr(items[1], col))

        # check descending sorts
        for col in COLS:
            r = self.client.get(self.url + f"?ut_sort=-{col}")  # note the -ve sign
            items = r.context["assigned_tickets"].object_list
            self.assertGreaterEqual(getattr(items[0], col), getattr(items[1], col))

    def test_unassigned_tickets_sort(self):
        # Arrange: we create two extra unassigned tickets
        _ = Ticket.objects.create(title="Bad shipment", queue=self.queue)
        _ = Ticket.objects.create(title="Late order", queue=self.queue)

        COLS = ("id", "priority", "created")

        self.client.force_login(self.user)

        # Act and assert
        # check ascending sorts
        for col in COLS:
            r = self.client.get(self.url + f"?una_sort={col}")
            items = r.context["unassigned_tickets"].object_list
            self.assertLessEqual(getattr(items[0], col), getattr(items[1], col))

        # check descending sorts
        for col in COLS:
            r = self.client.get(self.url + f"?una_sort=-{col}")  # note the -ve sign
            items = r.context["unassigned_tickets"].object_list
            self.assertGreaterEqual(getattr(items[0], col), getattr(items[1], col))

    def test_resolved_tickets_sort(self):
        # Arrange: we create two extra resolved tickets for alice
        for title in ("Bad shipment", "Late order"):
            _ = Ticket.objects.create(
                title=title,
                queue=self.queue,
                status=hd_settings.CLOSED_STATUS,
                assigned_to=self.user,
            )

        COLS = ("id", "priority", "status", "modified")

        self.client.force_login(self.user)

        # Act and assert
        # check ascending sorts
        for col in COLS:
            r = self.client.get(self.url + f"?utcr_sort={col}")
            items = r.context["closed_tickets"].object_list
            self.assertLessEqual(getattr(items[0], col), getattr(items[1], col))

        # check descending sorts
        for col in COLS:
            r = self.client.get(self.url + f"?utcr_sort=-{col}")  # note the -ve sign
            items = r.context["closed_tickets"].object_list
            self.assertGreaterEqual(getattr(items[0], col), getattr(items[1], col))
