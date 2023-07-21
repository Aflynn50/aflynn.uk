---
title: "SQLair Introduction"
date: 2023-07-19T11:48:47+01:00
---
# SQLair

So you want to access your database from Go. Well, there are a few options. The natural place to start is with Go's standard database library `database/sql`. Developed by the core Go team this library serves as an excellent starting point for building your queries. You can construct and execute your queries with relative ease, but then problems start to appear when you try and read the results from the database back into your program. Each row of the results has to be manually looped through and explicitly scanned into each field of each struct in which you are placing the result.

The way around all the hard manual labour? An [ORM](https://en.wikipedia.org/wiki/Object%E2%80%93relational_mapping)! Of course an ORM will solve your problem, but it does come with its own drawbacks. When it comes to executing complicated queries it can be more of a hindrance than a help and navigating an ORMs API can be almost like learning a new language.

If only it was possible to write your queries in SQL, but still get all the benefits of convenient type mapping...

### An introduction to SQLair

SQLair is a package for Go that provides type mapping between structs/maps and SQL databases by allowing references to the Go types within the SQL query itself.

This tutorial will take you through the basics of writing queries with SQLair and give you a taste of what is possible.

As a simple example, given Go structs `Employee` and `Team`, instead of the SQL query:

```plaintext
SELECT id, team_id, name
FROM employee
WHERE team_id = ?
```

With SQLair you could write:
```plaintext
SELECT &Employee.*
FROM employee
WHERE team_id = $Location.team_id
```

SQLair adds special *expressions* to your SQL statements. These expressions allow you to reference the source/destination Go types directly in the SQL query, meaning that you can work the purpose of a query in the context of your program from a single glance.

SQLair uses the [`database/sql`](https://pkg.go.dev/database/sql) package to interact with the database underneath. It provides a convenience layer on top.

The full API docs can be found at [pkg.go.dev](https://pkg.go.dev/github.com/canonical/sqlair).

In this introduction we will use the example of a company database containing employees and their teams. A full code example is given at the end of this post.

## Tagging structs

The first step is to tag the fields your structs with column names. The `db` tag is used to indicate to SQLair which database column a struct field corresponds to.

For example:

```go
type Employee struct {
	Name   string `db:"name"`
	ID     int    `db:"id"`
	TeamID int    `db:"team_id"`
}
```

All struct fields that correspond to a column and are used with SQLair should be tagged with the `db` tag. If a field of the struct does not correspond to a database column it can be left untagged and it will be ignored by SQLair.

It is important to note that SQLair *needs* the struct fields to be public in to order read from them and write to them.

## Writing the SQL
### SQLair Prepare

To build a query a statement first needs to be prepared. The `sqlair.Prepare` function takes a query with SQLair expressions in it and returns a `sqlair.Statement`. These statements are not tied to any database and can be created at the start of the program for use later on.

```go
stmt, err := sqlair.Prepare(`
    SELECT &Employee.*
    FROM person
    WHERE team = $Manager.team_id`,
    Employee{}, Manager{},
)
```

*Note:* `sqlair.Prepare` does not prepare the statement on the database. This is done automatically behind the scenes when the query is built on a `DB`.

The `Prepare` function needs a sample of every struct mentioned in the query. It uses the struct's reflection information to generate the columns and check that the expressions make sense. These structs are only used for type information, their content is disregarded.

There is also a function `sqlair.MustPrepare` that does not return an error and panics if it encounters one.

*Note:* To use the same struct twice in a query one of the types needs to be renamed e.g. `type Manager Person`

### Input and output expressions

In the SQLair expressions, the characters `$` and `&` are used to specify input and outputs respectively. The dollar `$` specifies a struct to fetch and argument from and the ampersand `&` specifies a struct to read query results into.

#### Input expressions

SQLair Input expressions replace parameter placeholders (`?`) and named parameters (`@Name`) in the SQL statement. An input expression is made up of the struct type name and a column name taken from the `db` tag of a struct field. For example:

```plaintext
UPDATE employee 
SET name = $Empolyee.name
WHERE id = $Employee.id"
```

The expression `$Employee.name` tells SQLair that when we create the query we will give it an `Employee` struct and that the `Name` field is passed as a query argument.

*Note:* we use the column name from the `db` tag, *not* the struct field name after the type.

#### Output expressions

Output expressions replace the columns in a SQL query. Because the struct is already  tagged, you can use an asterisk (`*`) to tell SQLair that you want to fetch and fill all the columns for that struct.

Here, it will use the reflection information of the sample `Employee` struct passed to `Prepare` to determine the columns to fetch.

```go
stmt, err := sqlair.Prepare(`
    SELECT &Employee.*
    FROM employee`,
    Employee{},
)
```

There are other more complex forms of output expressions as well. You can specify exactly which columns you want, and which table to get them from. 

```go
stmt, err := sqlair.Prepare(`
		SELECT e.* AS &Employee.*, (t.team_name, t.id) AS &Team.*
		FROM employees AS e, teams AS t
		WHERE t.room_id = $Location.room_id AND t.id = e.team_id`,
	Location{}, Employee{},
)
```

Or, if the columns on a particular table don't match the tags on the structs, you can rename them:

```go
stmt, err := sqlair.Prepare(`
	SELECT (manager_name, manager_team) AS (&Employee.name, &Employee.team)
	FROM managers`,
	Employee{},
)
```

Again, it is important to note that the we always use the column names found in the `db` tags of the struct to talk about a field in an output expression.

## Wrapping the database

SQLair does not handle configuring and opening a connection to the database. For this, you need to use `database/sql`. Once you have created a database object of type `*sql.DB` this can be wrapped with `sqlair.NewDB`.

If you want to just try out SQLair the Go `sqlite3` driver makes it very easy to set up an in memory database:

```go
import (
	"database/sql"
	"github.com/canonical/sqlair"
	_ "github.com/mattn/go-sqlite3"
)

sqldb, err := sql.Open("sqlite3", "file:test.db?cache=shared&mode=memory")
if err != nil {
	panic(err)
}

db := sqlair.NewDB(sqldb)
```

## Querying the database

Now you have your database its time to write a query. Assuming that `stmt` had one argument

```go
stmt := sqlair.MustPrepare(`
	SELECT &Employee.*
	FROM employees
	WHERE team_id = $Manager.team_id
`)

pedro := Manager{Name: "Pedro", ID: 4, TeamID: 2}
q := db.Query(ctx, stmt, pedro)
```

The `DB.Query` method takes a `context.Context` as its first argument so the query can be stopped if taking too long. The context (`ctx`) can be `nil` if no context is needed for the query.

It then takes the `*sqlair.Statement` followed by any query arguments. These arguments are all the structs mentioned in SQLair input expressions e.g. the `Person` struct corresponding to the expression `$Person.name` in the query.

A query object is designed to be used once then discarded.

### Getting the results

Running `db.Query` does not actually execute the query on the database. That happens when you do `Run`, `Get`, `GetAll` or `Iter` on the `Query`. 

*Note:* If the query has no output expressions (i.e. nothing of the form `&MyStruct...`) then no results will be fetched from the database. This can be confusing for new users because SQL statements such as `SELECT name FROM person` will not work if executed with SQLair; an output expression is needed: `SELECT &Person.name FROM person`.

`Get` fetches a single row from the database and reads the result into its arguments.

```go
var e = Employee{}
err := db.Query(ctx, stmt, pedro).Get(&e)
// e == Employee{Name: "Alastair", ID: 1, TeamID: 1} 
```


`GetAll` fetches all the result rows from the database. It takes a slice of structs for each argument.

```go
var es = []Employee{}
err := db.Query(ctx, stmt, pedro).GetAll(&es)
// es == []Employee{
//         Employee{ID: 1, TeamID: 1, Name: "Alastair"},
//         Employee{ID: 2, TeamID: 1, Name: "Ed"},
//         ...
// }
```


`Iter` returns an `Iterator` that fetches one row at a time. `Iter.Next` checks returns true if there is a next row. And once the iteration has finished `Iter.Close` must be called. This will also return any errors that happened during iteration.

```go
iter := db.Query(ctx, stmt, pedro).Iter()
for iter.Next() {
	var e = Employee{}
	err := iter.Get(&e)
	// e == Employee{Name: "Alastair", ID: 1, TeamID: 1} 
	if err != nil {
		// Handle error.
	}
	// Do something with e.
}
err := iter.Close()
```


`Run` runs a query on the DB. It is the same as `Get` with no arguments.

```go
stmt := sqlair.MustPrepare(`
	INSERT INTO person (name, id, team_id)
	VALUES ($Employee.name, $Employee.id, $Employee.team_id);`,
    Employee{},
)

var e = Employee{Name: "Alastair", ID: 1, TeamID: 1} 
err := db.Query(ctx, stmt, e).Run()
```

## Maps

SQLair supports maps as well as structs. So far in this introduction all examples have used structs to keep it simple, but in nearly all cases maps can be used as well.

For example:

```go
stmt := sqlair.MustPrepare(`
	SELECT (name, team_id) AS &M.*
	FROM employee
	WHERE id = $M.pid
`, sqlair.M{})

var m = sqlair.M{}
err := db.Query(ctx, stmt, sqlair.M{"pid": 1}).Get(m)
// m == sqlair.M{"name": "Alastair", "team_id": 1}
```

The type `sqlair.M` seen here is simply the type `map[string]any`. To reference it in the query however, it needs a name which is why SQLair provides this builtin. The `sqlair.M` type is not special in any way; any named map with a key type of `string` can be used with a SQLair query.

When using a map in an output expression, the query results are stored in the map with the column name as the key. In input expressions, the argument is specified by the map key.

It is not permitted to use a map with an asterisk and no columns specified e.g. `SELECT &M.* FROM employee`. The columns always have to be specified. 

## Transactions

Transactions are also supported by SQLair. A transaction can be started with:
```go
tx, err := db.Begin(ctx, txOpts)
if err != nil {
	// Handle error.
}
```

The second argument to `Begin` contains the optional settings for the transaction. It is a pointer to a `sqlair.TXOptions` which can be created with the desired settings:

```go
tx, err := db.Begin(ctx, &sqlair.TXOptions{Isolation: 0, ReadOnly: false})
```

To use the default settings set `nil` can be passed as the second parameter.

Queries are run on a transaction just like they are run on the database. The transaction is finished with a `tx.Commit` or a `tx.Rollback`.

```go
err = tx.Query(ctx, stmt, e).Run()
if err != nil {
	// Handle error.
}
err = tx.Commit()
if err != nil {
	// Handle error.
}
```

Remember to always commit or rollback a transaction to finish it and apply it to the database.

## Wrapping up

There are new features being added to SQLair all the time, I intend to write more tutorials as these features are added, as well as more in depth articles on specific features and gnarly problems.

Hopefully this has been of some use, enjoy using the library!

## A complete example

```go
func Example() {
	sqldb, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		panic(err)
	}

	db := sqlair.NewDB(sqldb)
	create := sqlair.MustPrepare(`
	CREATE TABLE locations (
		room_id integer,
		room_name text
	);
	CREATE TABLE employees (
		id integer,
		team_id integer,
		name text
	);
	CREATE TABLE teams (
		id integer,
		room_id integer,
		team_name text
	)`)
	err = db.Query(nil, create).Run()
	if err != nil {
		panic(err)
	}

	// Statement to populate the locations table.
	insertLocation := sqlair.MustPrepare(`
		INSERT INTO locations (room_name, room_id) 
		VALUES ($Location.room_name, $Location.room_id)`,
		Location{},
	)

	var l1 = Location{ID: 1, Name: "The Basement"}
	var l2 = Location{ID: 2, Name: "Court"}
	var l3 = Location{ID: 3, Name: "The Market"}
	var l4 = Location{ID: 4, Name: "The Bar"}
	var l5 = Location{ID: 5, Name: "The Penthouse"}
	var locations = []Location{l1, l2, l3, l4, l5}
	for _, l := range locations {
		err := db.Query(nil, insertLocation, l).Run()
		if err != nil {
			panic(err)
		}
	}

	// Statement to populate the employees table.
	insertEmployee := sqlair.MustPrepare(`
		INSERT INTO employees (id, name, team_id)
		VALUES ($Employee.id, $Employee.name, $Employee.team_id);`,
		Employee{},
	)

	var e1 = Employee{ID: 1, TeamID: 1, Name: "Alastair"}
	var e2 = Employee{ID: 2, TeamID: 1, Name: "Ed"}
	var e3 = Employee{ID: 3, TeamID: 1, Name: "Marco"}
	var e4 = Employee{ID: 4, TeamID: 2, Name: "Pedro"}
	var e5 = Employee{ID: 5, TeamID: 3, Name: "Serdar"}
	var e6 = Employee{ID: 6, TeamID: 3, Name: "Lina"}
	var e7 = Employee{ID: 7, TeamID: 4, Name: "Joe"}
	var e8 = Employee{ID: 8, TeamID: 5, Name: "Ben"}
	var e9 = Employee{ID: 9, TeamID: 5, Name: "Jenny"}
	var e10 = Employee{ID: 10, TeamID: 6, Name: "Sam"}
	var e11 = Employee{ID: 11, TeamID: 7, Name: "Melody"}
	var e12 = Employee{ID: 12, TeamID: 8, Name: "Mark"}
	var e13 = Employee{ID: 13, TeamID: 8, Name: "Gustavo"}
	var employees = []Employee{e1, e2, e3, e4, e5, e6, e7, e8, e9, e10, e11, e12, e13}
	for _, e := range employees {
		err := db.Query(nil, insertEmployee, e).Run()
		if err != nil {
			panic(err)
		}
	}

	// Statement to populate the teams table.
	insertTeam := sqlair.MustPrepare(`
		INSERT INTO teams (id, team_name, room_id)
		VALUES ($Team.id, $Team.team_name, $Team.room_id);`,
		Team{},
	)

	var t1 = Team{ID: 1, RoomID: 1, Name: "Engineering"}
	var t2 = Team{ID: 2, RoomID: 1, Name: "Management"}
	var t3 = Team{ID: 3, RoomID: 1, Name: "Presentation Engineering"}
	var t4 = Team{ID: 4, RoomID: 2, Name: "Marketing"}
	var t5 = Team{ID: 5, RoomID: 3, Name: "Legal"}
	var t6 = Team{ID: 6, RoomID: 3, Name: "HR"}
	var t7 = Team{ID: 7, RoomID: 4, Name: "Sales"}
	var t8 = Team{ID: 8, RoomID: 5, Name: "Leadership"}
	var teams = []Team{t1, t2, t3, t4, t5, t6, t7, t8}
	for _, t := range teams {
		err := db.Query(nil, insertTeam, t).Run()
		if err != nil {
			panic(err)
		}
	}

	// Example 1
	// Find the team the employee 1 works in.
	selectSomeoneInTeam := sqlair.MustPrepare(`
		SELECT &Team.*
		FROM teams
		WHERE id = $Employee.team_id`,
		Employee{}, Team{},
	)

	// Get returns a single result.
	var team = Team{}
	err = db.Query(nil, selectSomeoneInTeam, e1).Get(&team)
	if err != nil {
		panic(err)
	}

	fmt.Printf("%s is on the %s team.\n", e1.Name, team.Name)

	// Example 2
	// Find out who is in location l1 and what team they work for.
	selectPeopleInRoom := sqlair.MustPrepare(`
		SELECT e.* AS &Employee.*, (t.team_name, t.id) AS &Team.*
		FROM employees AS e, teams AS t
		WHERE t.room_id = $Location.room_id AND t.id = e.team_id`,
		Employee{}, Team{}, Location{},
	)

	// GetAll returns all the results.
	var roomDwellers = []Employee{}
	var dwellersTeams = []Team{}
	err = db.Query(nil, selectPeopleInRoom, l1).GetAll(&roomDwellers, &dwellersTeams)
	if err != nil {
		panic(err)
	}

	for i := range roomDwellers {
		fmt.Printf("%s (%s), ", roomDwellers[i].Name, dwellersTeams[i].Name)
	}
	fmt.Printf("are in %s.\n", l1.Name)

	// Example 3
	// Cycle through employees until we find one in the Penthouse.

	// A map with a key type of string is used to
	// pass arguments that are not fields of structs.
	// sqlair.M is of type map[string]any but if
	// the map has a key type of string it can be used.
	selectPeopleAndRoom := sqlair.MustPrepare(`
		SELECT (e.name, t.team_name, l.room_name) AS (&M.employee_name, &M.team, &M.location)
		FROM locations AS l
		JOIN teams AS t
		ON t.room_id = l.room_id
		JOIN employees AS e
		ON e.team_id = t.id`,
		sqlair.M{},
	)

	// Results can be iterated through with an Iterable.
	// iter.Next prepares the next result.
	// iter.Get reads it into structs.
	// iter.Close closes the query returning any errors. It must be called after iteration is finished.
	iter := db.Query(nil, selectPeopleAndRoom).Iter()
	defer iter.Close()
	for iter.Next() {
		var m = sqlair.M{}
		err := iter.Get(&m)
		if err != nil {
			panic(err)
		}
		if m["location"] == "The Penthouse" {
			fmt.Printf("%s from team %s is in %s.\n", m["employee_name"], m["team"], m["location"])
			break
		}
	}
	err = iter.Close()
	if err != nil {
		panic(err)
	}

	drop := sqlair.MustPrepare(`
		DROP TABLE employees;
		DROP TABLE teams;
		DROP TABLE locations;`,
	)
	err = db.Query(nil, drop).Run()
	if err != nil {
		panic(err)
	}

	// Output:
	//Alastair is on the Engineering team.
	//Alastair (Engineering), Ed (Engineering), Marco (Engineering), Pedro (Management), Serdar (Presentation Engineering), Lina (Presentation Engineering), are in The Basement.
	//Gustavo from team Leadership is in The Penthouse.
}
```

